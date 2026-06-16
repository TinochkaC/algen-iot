"""
analyze_algae_vitality.py - Algen-IoT
=====================================

Periodische Bewertung der Algenvitalitaet alle 300 Sekunden.

Vorgehen (Datenflussarchitektur Kapitel 3.2 + 4.2.1.B):
  1. Aus algen_bio die letzten 300s an Reaktor-Sensordaten holen.
  2. Mittelwerte und Status-Aggregat berechnen.
  3. vitality_score (Stufe 0-4) und growth_status (Stufe 5) bestimmen,
     dazu wird der Trueb-Mittelwert mit dem vorherigen 300s-Fenster
     verglichen (Wachstumsrate).
  4. Ergebnis-JSON in MEASUREMENT_ANALYSIS_ALGAE schreiben.
  5. Bei eingehendem Sensor-Alarm sofort einen ausserplanmaessigen
     Analyse-Lauf ausloesen (is_emergency_run = true).

Autor: Algen-IoT Team
Datum: 2026-05-31
"""

import signal
import sys
import threading
from collections import Counter
from typing import Optional

from algen_iot_core import (
    core_constants,
    core_database,
    core_logger,
    core_math,
    core_mqtt,
    core_utils,
)


_logger = core_logger.get_logger(
    "analyze_algae_vitality",
    log_file_path=f"{core_constants.LOG_DIRECTORY_DEFAULT}/analyze_algae_vitality.log",
)


# =============================================================================
# STATE
# =============================================================================
_emergency_run_event = threading.Event()
_is_emergency_run = False


# =============================================================================
# AGGREGATION (Datenflussarch. 4.2.1.B Stufe 1)
# =============================================================================

def aggregate_window(start_timestamp: int,
                     end_timestamp: int) -> tuple[dict, dict]:
    """Aggregiert ein Zeitfenster zu Mittelwerten + Status-Aggregaten.

    Args:
        start_timestamp: Beginn (UNIX-Sekunden, inklusiv).
        end_timestamp:   Ende  (UNIX-Sekunden, exklusiv).

    Returns:
        tuple[dict, dict]:
            (aggregated_data, status_data)
            aggregated_data: {"avg_water_temp": ..., "avg_ph": ..., ...}
            status_data:     {"water_temp_status": ..., "ph_status": ..., ...}
    """
    aggregated: dict = {}
    statuses: dict = {}

    for sensor_name in core_constants.SENSORS_REACTOR:
        value_records = core_database.db_get_records_by_timeframe(
            table_name=core_constants.MEASUREMENT_REACTOR_SENSORS,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            field_name=sensor_name,
        )
        status_records = core_database.db_get_records_by_timeframe(
            table_name=core_constants.MEASUREMENT_REACTOR_SENSORS,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            field_name=f"{sensor_name}_status",
        )

        values = [r["value"] for r in value_records
                  if isinstance(r.get("value"), (int, float))]
        aggregated[f"avg_{sensor_name}"] = core_math.calculate_average(values)

        # Aggregat-Status nach Worst-Case-Regel:
        # sensor_error > error > warning > normal
        status_values = [r["value"] for r in status_records
                         if isinstance(r.get("value"), str)]
        statuses[f"{sensor_name}_status"] = _worst_case_status(status_values)

    return aggregated, statuses


def _worst_case_status(status_values: list[str]) -> str:
    """Liefert den 'schlimmsten' Status aus einer Liste.

    Reihenfolge der Severitaet (absteigend):
        sensor_error > error > warning > normal
    """
    if not status_values:
        return core_constants.DATA_STATUS_NORMAL

    priority = {
        core_constants.DATA_STATUS_SENSOR_ERROR: 3,
        core_constants.DATA_STATUS_ERROR:        2,
        core_constants.DATA_STATUS_WARNING:      1,
        core_constants.DATA_STATUS_NORMAL:       0,
    }
    return max(status_values, key=lambda s: priority.get(s, 0))


# =============================================================================
# EIN ANALYSE-DURCHLAUF
# =============================================================================

def run_one_analysis() -> None:
    """Ein vollstaendiger Analyse-Zyklus."""
    global _is_emergency_run

    now_ts = core_utils.get_current_timestamp()
    window_s = core_constants.ANALYSIS_INTERVAL_S

    # Aktuelles Fenster
    current_agg, current_status = aggregate_window(
        start_timestamp=now_ts - window_s,
        end_timestamp=now_ts,
    )

    # Vorheriges Fenster - nur zur Wachstumsraten-Berechnung
    previous_agg, _ = aggregate_window(
        start_timestamp=now_ts - 2 * window_s,
        end_timestamp=now_ts - window_s,
    )
    turbidity_old: Optional[float] = previous_agg.get("avg_turbidity")

    if all(v is None for v in current_agg.values()):
        _logger.warning("Aktuelles 300s-Fenster enthaelt keine Daten - "
                        "Analyse wird uebersprungen.")
        _is_emergency_run = False
        return

    # Mathematische Auswertung
    evaluation = core_math.evaluate_full_algae_vitality(
        aggregated_data=current_agg,
        status_data=current_status,
        turbidity_old=turbidity_old,
    )

    # Spec-konformes Analyse-JSON
    payload = core_utils.build_standard_json(
        id_prefix=core_constants.UUID_PREFIX_ALGAE_ANALYSIS,
        parameters_dict={
            "is_emergency_run": _is_emergency_run,
            "vitality_score":   evaluation["vitality_score"],
            "growth_status":    evaluation["growth_status"],
            "details": {
                "avg_water_temp":      _round(current_agg.get("avg_water_temp")),
                "avg_ph":              _round(current_agg.get("avg_ph")),
                "avg_turbidity":       _round(current_agg.get("avg_turbidity")),
                "avg_light_intensity": _round(current_agg.get("avg_light_intensity")),
                "turbidity_previous":  _round(turbidity_old),
            },
        },
        id_field_name="analysis_id",
    )

    success = core_database.db_insert_record(
        table_name=core_constants.MEASUREMENT_ANALYSIS_ALGAE,
        json_payload=payload,
    )
    if success:
        _logger.info(
            "Algen-Analyse OK: vitality=%.2f growth=%s emergency=%s.",
            evaluation["vitality_score"],
            evaluation["growth_status"],
            _is_emergency_run,
        )
    else:
        _logger.error("Algen-Analyse konnte NICHT gespeichert werden.")

    # Emergency-Modus immer zuruecksetzen nach Verarbeitung
    _is_emergency_run = False


def _round(value: Optional[float]) -> Optional[float]:
    """Rundet auf 2 Nachkommastellen, behaelt None bei."""
    return None if value is None else round(value, 2)


# =============================================================================
# ALARM-CALLBACK (loest emergency_run aus)
# =============================================================================

def on_sensor_alarm(topic: str, payload: dict) -> None:
    """Subscription-Callback fuer pbr/reactor-01/alarm/sensor/+.

    Setzt das Emergency-Flag und unterbricht das 300s-Warten, damit der
    naechste Analyse-Lauf sofort startet.
    """
    global _is_emergency_run

    parts = topic.split("/")
    if len(parts) != 5 or parts[2] != "alarm" or parts[3] != "sensor":
        return

    # Nur reaktor-spezifische Alarme triggern diese Analyse
    device_id = parts[1]
    if device_id != core_constants.REACTOR_DEVICE_ID:
        return

    sensor_name = parts[4]
    if sensor_name not in core_constants.SENSORS_REACTOR:
        return

    _logger.warning("Sensor-Alarm empfangen (%s): emergency_run wird ausgeloest.",
                    sensor_name)
    _is_emergency_run = True
    _emergency_run_event.set()


# =============================================================================
# MAIN
# =============================================================================

def _shutdown() -> None:
    core_mqtt.mqtt_disconnect()
    core_database.close()


def main() -> int:
    """Endlosschleife mit Wakeup auf emergency_run_event."""
    alarm_pattern = core_constants.TOPIC_TEMPLATE_ALARM_SENSOR.format(
        device_id=core_constants.REACTOR_DEVICE_ID,
        sensor_name="+",
    )
    if not core_mqtt.mqtt_subscribe_topic(alarm_pattern, on_sensor_alarm):
        _logger.error("MQTT-Subscribe fehlgeschlagen - Abbruch.")
        return 1
    core_mqtt.mqtt_start_loop(blocking=False)  # nicht-blockierend - MQTT im Hintergrund

    def _handle_signal(signum, _frame):
        _logger.info("Signal %s empfangen - Skript wird beendet.", signum)
        _emergency_run_event.set()  # Schleife aufwecken
        _shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    _logger.info("Algen-Analyse gestartet (Intervall %ds).",
                 core_constants.ANALYSIS_INTERVAL_S)

    while True:
        try:
            run_one_analysis()
        except Exception as exc:
            _logger.error("Unerwarteter Fehler in der Analyse: %s",
                          exc, exc_info=True)

        # Warten: regulaer 300s ODER bis ein Alarm das Event aufweckt
        _emergency_run_event.wait(timeout=core_constants.ANALYSIS_INTERVAL_S)
        _emergency_run_event.clear()


if __name__ == "__main__":
    sys.exit(main())
