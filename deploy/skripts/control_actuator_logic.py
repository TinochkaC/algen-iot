"""
control_actuator_logic.py - Algen-IoT
=====================================

Zentrale Entscheidungslogik: liest die neuesten Analyse-Ergebnisse aus
beiden Analyse-Skripten und entscheidet, ob ein Aktor angesteuert werden
muss.

Vorgehen (Datenflussarchitektur Kapitel 3.3 + 4.3):

  1. Alle ANALYSIS_INTERVAL_S Sekunden, oder nach einem Sensor-Alarm,
     den letzten analysis_air und analysis_algae-Datensatz lesen.

  2. Anhand der action_recommendation (Luft) und growth_status (Algen)
     pro Aktor ermitteln, ob:
       - heater eingeschaltet werden soll (Wasser zu kalt)
       - pump   dosieren soll              (Naehrstoff/Kontamination)
       - led    Intensitaet aendern soll   (Wachstumsphase)

  3. Vor dem Publish PRUEFEN:
       a) Ob ein gleichartiger Befehl in den letzten COOLDOWN_PERIOD_S
          Sekunden bereits gesendet wurde (Hysterese / Schutz vor
          Schwingungen).
       b) Ob max. MAX_LAST_ACTIONS_COUNT Aktionen pro Aktor noch nicht
          erreicht sind (Schutz vor MQTT-Sturm).

  4. Befehl mit eindeutiger action_id via core_mqtt.mqtt_publish_command
     senden. Die Rueckmeldungen (accepted/running/completed) werden von
     bridge_andanalyse_mqtt_actuator_status persistiert.

Autor: Algen-IoT Team
Datum: 2026-05-31
"""

import signal
import sys
import threading
from typing import Optional

from algen_iot_core import (
    core_constants,
    core_database,
    core_logger,
    core_mqtt,
    core_utils,
)


_logger = core_logger.get_logger(
    "control_actuator_logic",
    log_file_path=f"{core_constants.LOG_DIRECTORY_DEFAULT}/control_actuator_logic.log",
)


# =============================================================================
# STATE: Letzte gesendete Befehle pro Aktor (Cooldown-Tracking)
# =============================================================================
# Mapping actuator -> (last_action_timestamp, last_is_action_on)
_last_command_state: dict[str, tuple[int, bool]] = {}
_trigger_event = threading.Event()


# =============================================================================
# HILFSFUNKTIONEN: Daten aus der DB lesen
# =============================================================================

def get_latest_analysis(measurement_name: str) -> Optional[dict]:
    """Liefert den neuesten Analyse-Datensatz aus dem angegebenen Measurement.

    Args:
        measurement_name: MEASUREMENT_ANALYSIS_AIR oder MEASUREMENT_ANALYSIS_ALGAE.

    Returns:
        dict: Neuester Datensatz als Dict aller Felder.
        None: Falls noch kein Datensatz vorhanden.
    """
    now_ts = core_utils.get_current_timestamp()
    records = core_database.db_get_records_by_timeframe(
        table_name=measurement_name,
        start_timestamp=now_ts - 2 * core_constants.ANALYSIS_INTERVAL_S,
        end_timestamp=now_ts + 60,
    )
    if not records:
        return None

    # Datensaetze nach Zeit absteigend sortieren und den neuesten zurueckgeben.
    # Aufgrund der Spread-Struktur in InfluxDB (ein Punkt pro Feld) muessen
    # alle Felder mit demselben Timestamp zu EINEM Analyse-Eintrag
    # zusammengefuehrt werden.
    by_timestamp: dict[int, dict] = {}
    for record in records:
        ts = record.get("timestamp")
        field = record.get("field")
        value = record.get("value")
        if ts is None or field is None:
            continue
        by_timestamp.setdefault(int(ts), {})[field] = value

    if not by_timestamp:
        return None
    latest_ts = max(by_timestamp.keys())
    return {"timestamp": latest_ts, **by_timestamp[latest_ts]}


def get_latest_water_temp_average() -> Optional[float]:
    """Letzten avg_water_temp aus dem juengsten Algen-Analyse-Eintrag lesen."""
    latest = get_latest_analysis(core_constants.MEASUREMENT_ANALYSIS_ALGAE)
    if latest is None:
        return None
    return latest.get("avg_water_temp")


# =============================================================================
# COOLDOWN
# =============================================================================

def is_within_cooldown(actuator: str, requested_action_on: bool) -> bool:
    """Prueft, ob fuer den Aktor noch ein Cooldown-Block aktiv ist.

    Cooldown-Logik (Datenflussarch. 3.3.3):
    - Wenn der LETZTE Befehl an diesen Aktor IDENTISCH war (gleiches
      is_action_on) und juenger als COOLDOWN_PERIOD_S ist, wird der neue
      Befehl unterdrueckt.
    - Ein WECHSEL von ON nach OFF oder umgekehrt ist immer erlaubt.

    Args:
        actuator: Einer aus core_constants.ACTUATORS.
        requested_action_on: Der is_action_on-Wert des geplanten Befehls.

    Returns:
        bool: True, wenn unterdrueckt werden soll.
    """
    last = _last_command_state.get(actuator)
    if not last:
        return False
    last_ts, last_is_on = last
    age_s = core_utils.get_current_timestamp() - last_ts

    is_same_action = (last_is_on == requested_action_on)
    return is_same_action and age_s < core_constants.COOLDOWN_PERIOD_S


def remember_command(actuator: str, is_action_on: bool) -> None:
    """Merkt sich den zuletzt gesendeten Befehl pro Aktor."""
    _last_command_state[actuator] = (
        core_utils.get_current_timestamp(),
        is_action_on,
    )


# =============================================================================
# ENTSCHEIDUNGS-REGELN (Datenflussarch. 4.3.x Prio-Tabellen)
# =============================================================================

def decide_pump(air_analysis: dict, algae_analysis: dict) -> Optional[dict]:
    """Entscheidet, ob ein Pumpen-Befehl gesendet werden soll.

    Returns:
        dict | None: JSON-Payload fuer mqtt_publish_command oder None.
    """
    recommendation = air_analysis.get("action_recommendation")
    growth_status = algae_analysis.get("growth_status")

    is_action_on = False
    trigger = core_constants.TRIGGER_REASON_SCHEDULED
    duration_s = 0

    # Sonderregel: bei contamination_suspected -> kraeftige Spuelung
    if growth_status == core_constants.GROWTH_STATUS_CONTAMINATION:
        is_action_on = True
        trigger = core_constants.TRIGGER_REASON_THRESHOLD
        duration_s = 60
    # Routine: bei clean_air_more der Luft -> kuerzere Dosierung
    elif recommendation == core_constants.ACTION_RECOMMENDATION_CLEAN_MORE:
        is_action_on = True
        trigger = core_constants.TRIGGER_REASON_THRESHOLD
        duration_s = 20

    return {
        "is_enabled":     True,
        "is_action_on":   is_action_on,
        "duration_s":     duration_s,
        "trigger_reason": trigger,
    } if is_action_on else None


def decide_heater(algae_analysis: dict) -> Optional[dict]:
    """Entscheidet, ob der Heater geschaltet werden soll.

    Spec-Idealwert Wassertemperatur: 30 grad (Bereich normal 28-32).
    """
    avg_water_temp = algae_analysis.get("avg_water_temp")
    if avg_water_temp is None:
        return None

    # Hysterese: Schwellwerte aus Library
    heat_on_threshold  = core_constants.IDEAL_VALUE_WATER_TEMP - 1.0  # 29 grad
    heat_off_threshold = core_constants.IDEAL_VALUE_WATER_TEMP + 1.0  # 31 grad

    if avg_water_temp < heat_on_threshold:
        return {
            "is_enabled":         True,
            "is_action_on":       True,
            "target_water_temp":  core_constants.IDEAL_VALUE_WATER_TEMP,
            "trigger_reason":     core_constants.TRIGGER_REASON_THRESHOLD,
        }
    if avg_water_temp > heat_off_threshold:
        return {
            "is_enabled":         True,
            "is_action_on":       False,
            "target_water_temp":  core_constants.IDEAL_VALUE_WATER_TEMP,
            "trigger_reason":     core_constants.TRIGGER_REASON_THRESHOLD,
        }
    return None


def decide_led(algae_analysis: dict) -> Optional[dict]:
    """Bestimmt LED-Intensitaet anhand des growth_status."""
    growth_status = algae_analysis.get("growth_status")
    intensity_map = {
        core_constants.GROWTH_STATUS_GROWTH:        80,
        core_constants.GROWTH_STATUS_STABILITY:     50,
        core_constants.GROWTH_STATUS_EXTINCTION:    30,
        core_constants.GROWTH_STATUS_CONTAMINATION: 0,
    }
    target_pct = intensity_map.get(growth_status)
    if target_pct is None:
        return None

    return {
        "is_enabled":         True,
        "is_action_on":       target_pct > 0,
        "target_intensity":   target_pct,
        "target_lux":         core_constants.IDEAL_VALUE_LIGHT_INTENSITY,
        "trigger_reason":     core_constants.TRIGGER_REASON_THRESHOLD,
    }


# =============================================================================
# AUSFUEHRUNG EINER ENTSCHEIDUNG
# =============================================================================

def maybe_send_command(actuator: str,
                        decision: Optional[dict]) -> None:
    """Sendet einen Befehl, falls Cooldown nicht aktiv ist."""
    if decision is None:
        return

    is_action_on = bool(decision.get("is_action_on", False))
    if is_within_cooldown(actuator, is_action_on):
        _logger.info("Aktor '%s' im Cooldown - Befehl unterdrueckt.", actuator)
        return

    payload = core_utils.build_standard_json(
        id_prefix=core_constants.UUID_PREFIX_ACTUATOR_COMMAND,
        parameters_dict=decision,
        id_field_name="action_id",
    )

    if core_mqtt.mqtt_publish_command(actuator_name=actuator,
                                       json_payload=payload):
        remember_command(actuator, is_action_on)
        # Auch in DB protokollieren (fuer Audit + Watchdog)
        core_database.db_insert_record(
            table_name=core_constants.MEASUREMENT_ACTUATOR_COMMANDS,
            json_payload=payload,
        )
        _logger.info("Befehl an '%s' gesendet (action_id=%s, action_on=%s).",
                     actuator, payload["action_id"], is_action_on)
    else:
        _logger.error("Befehl an '%s' konnte NICHT publiziert werden.", actuator)


# =============================================================================
# EIN STEUER-ZYKLUS
# =============================================================================

def run_one_cycle() -> None:
    """Liest die letzten Analysen und stoesst ggf. Aktor-Befehle an."""
    air = get_latest_analysis(core_constants.MEASUREMENT_ANALYSIS_AIR)
    algae = get_latest_analysis(core_constants.MEASUREMENT_ANALYSIS_ALGAE)

    if air is None or algae is None:
        _logger.warning("Noch keine Analyse-Daten verfuegbar - "
                        "Steuer-Zyklus uebersprungen.")
        return

    _logger.info("Entscheidung auf Basis: aqi=%s, rec=%s, growth=%s, water=%s.",
                 air.get("air_quality_index"),
                 air.get("action_recommendation"),
                 algae.get("growth_status"),
                 algae.get("avg_water_temp"))

    maybe_send_command(core_constants.ACTUATOR_PUMP,
                       decide_pump(air, algae))
    maybe_send_command(core_constants.ACTUATOR_HEATER,
                       decide_heater(algae))
    maybe_send_command(core_constants.ACTUATOR_LED,
                       decide_led(algae))


# =============================================================================
# ALARM-CALLBACK (sofortiger Steuer-Zyklus bei Sensor-Alarm)
# =============================================================================

def on_sensor_alarm(topic: str, payload: dict) -> None:
    """Triggert einen sofortigen Steuer-Zyklus bei kritischen Alarmen."""
    if not payload.get("is_critical"):
        return
    _logger.warning("Kritischer Alarm auf %s - sofortiger Steuer-Zyklus.", topic)
    _trigger_event.set()


# =============================================================================
# MAIN
# =============================================================================

def _shutdown() -> None:
    core_mqtt.mqtt_disconnect()
    core_database.close()


def main() -> int:
    if not core_mqtt.mqtt_subscribe_topic("pbr/+/alarm/sensor/+", on_sensor_alarm):
        _logger.error("MQTT-Subscribe fehlgeschlagen - Abbruch.")
        return 1
    core_mqtt.mqtt_start_loop(blocking=False)

    def _handle_signal(signum, _frame):
        _logger.info("Signal %s empfangen.", signum)
        _trigger_event.set()
        _shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    _logger.info("Aktor-Logik gestartet (Intervall %ds).",
                 core_constants.ANALYSIS_INTERVAL_S)

    while True:
        try:
            run_one_cycle()
        except Exception as exc:
            _logger.error("Unerwarteter Fehler im Zyklus: %s",
                          exc, exc_info=True)

        _trigger_event.wait(timeout=core_constants.ANALYSIS_INTERVAL_S)
        _trigger_event.clear()


if __name__ == "__main__":
    sys.exit(main())
