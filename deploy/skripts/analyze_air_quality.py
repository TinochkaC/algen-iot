"""
analyze_air_quality.py - Algen-IoT
==================================

Periodische Bewertung der Raumluftqualitaet alle 300 Sekunden.

Vorgehen (Datenflussarchitektur Kapitel 3.2 + 4.2.1.A):
  1. Aus algen_bio die letzten 300s an Raumluft-Sensordaten holen
     (co2, voc, air_temp, humidity).
  2. Mittelwerte und Status-Aggregat berechnen.
  3. air_quality_index (Stufe 0-5) und action_recommendation (Stufe 6,
     inkl. Sonderregel CO2<300 und sensor_error->check_sensors) bestimmen.
  4. Ergebnis-JSON in MEASUREMENT_ANALYSIS_AIR schreiben.
  5. Bei eingehendem Sensor-Alarm sofort einen ausserplanmaessigen
     Analyse-Lauf ausloesen (is_emergency_run = true).

NOTE: Diese Datei ist der vollstaendige, spec-konforme Neuschrieb des
fehlerhaften analyze_air_quality.py-Skripts. Alle 12 P1-Verstoesse aus
dem Code-Review sind hier korrigiert.

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
    core_math,
    core_mqtt,
    core_utils,
)


_logger = core_logger.get_logger(
    "analyze_air_quality",
    log_file_path=f"{core_constants.LOG_DIRECTORY_DEFAULT}/analyze_air_quality.log",
)


# =============================================================================
# STATE
# =============================================================================
_emergency_run_event = threading.Event()
_is_emergency_run = False


# =============================================================================
# AGGREGATION
# =============================================================================

def aggregate_window(start_timestamp: int,
                     end_timestamp: int) -> tuple[dict, dict]:
    """Aggregiert die Raumluft-Sensordaten eines Zeitfensters.

    Returns:
        tuple[dict, dict]:
            aggregated_data: {avg_co2, avg_voc, avg_air_temp, avg_humidity}
            status_data:     {co2_status, voc_status, air_temp_status, humidity_status}
    """
    aggregated: dict = {}
    statuses: dict = {}

    for sensor_name in core_constants.SENSORS_ROOM:
        value_records = core_database.db_get_records_by_timeframe(
            table_name=core_constants.MEASUREMENT_ROOM_SENSORS,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            field_name=sensor_name,
        )
        status_records = core_database.db_get_records_by_timeframe(
            table_name=core_constants.MEASUREMENT_ROOM_SENSORS,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            field_name=f"{sensor_name}_status",
        )

        values = [r["value"] for r in value_records
                  if isinstance(r.get("value"), (int, float))]
        aggregated[f"avg_{sensor_name}"] = core_math.calculate_average(values)

        status_values = [r["value"] for r in status_records
                         if isinstance(r.get("value"), str)]
        statuses[f"{sensor_name}_status"] = _worst_case_status(status_values)

    return aggregated, statuses


def _worst_case_status(status_values: list[str]) -> str:
    """Worst-Case-Status fuer eine Liste (siehe analyze_algae_vitality.py)."""
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
    """Ein vollstaendiger Luftanalyse-Zyklus."""
    global _is_emergency_run

    now_ts = core_utils.get_current_timestamp()
    aggregated_data, status_data = aggregate_window(
        start_timestamp=now_ts - core_constants.ANALYSIS_INTERVAL_S,
        end_timestamp=now_ts,
    )

    if all(v is None for v in aggregated_data.values()):
        _logger.warning("Aktuelles 300s-Fenster enthaelt keine Daten - "
                        "Analyse wird uebersprungen.")
        _is_emergency_run = False
        return

    evaluation = core_math.evaluate_full_air_quality(
        aggregated_data=aggregated_data,
        status_data=status_data,
    )

    payload = core_utils.build_standard_json(
        id_prefix=core_constants.UUID_PREFIX_AIR_ANALYSIS,
        parameters_dict={
            "is_emergency_run":      _is_emergency_run,
            "air_quality_index":     evaluation["air_quality_index"],
            "action_recommendation": evaluation["action_recommendation"],
            "details": {
                "avg_co2":      _round(aggregated_data.get("avg_co2")),
                "avg_voc":      _round(aggregated_data.get("avg_voc")),
                "avg_air_temp": _round(aggregated_data.get("avg_air_temp")),
                "avg_humidity": _round(aggregated_data.get("avg_humidity")),
                "quality_index_numeric": evaluation.get("quality_index_numeric"),
            },
        },
        id_field_name="analysis_id",
    )

    success = core_database.db_insert_record(
        table_name=core_constants.MEASUREMENT_ANALYSIS_AIR,
        json_payload=payload,
    )
    if success:
        _logger.info(
            "Luft-Analyse OK: aqi=%s rec=%s emergency=%s.",
            evaluation["air_quality_index"],
            evaluation["action_recommendation"],
            _is_emergency_run,
        )
    else:
        _logger.error("Luft-Analyse konnte NICHT gespeichert werden.")

    _is_emergency_run = False


def _round(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value, 2)


# =============================================================================
# ALARM-CALLBACK
# =============================================================================

def on_sensor_alarm(topic: str, payload: dict) -> None:
    """Loest bei Raumluft-Sensor-Alarmen einen sofortigen Analyse-Lauf aus."""
    global _is_emergency_run

    parts = topic.split("/")
    if len(parts) != 5 or parts[2] != "alarm" or parts[3] != "sensor":
        return

    device_id = parts[1]
    if device_id != core_constants.ROOMNODE_DEVICE_ID:
        return

    sensor_name = parts[4]
    if sensor_name not in core_constants.SENSORS_ROOM:
        return

    _logger.warning("Raumluft-Alarm empfangen (%s): emergency_run.", sensor_name)
    _is_emergency_run = True
    _emergency_run_event.set()


# =============================================================================
# MAIN
# =============================================================================

def _shutdown() -> None:
    core_mqtt.mqtt_disconnect()
    core_database.close()


def main() -> int:
    alarm_pattern = core_constants.TOPIC_TEMPLATE_ALARM_SENSOR.format(
        device_id=core_constants.ROOMNODE_DEVICE_ID,
        sensor_name="+",
    )
    if not core_mqtt.mqtt_subscribe_topic(alarm_pattern, on_sensor_alarm):
        _logger.error("MQTT-Subscribe fehlgeschlagen - Abbruch.")
        return 1
    core_mqtt.mqtt_start_loop(blocking=False)

    def _handle_signal(signum, _frame):
        _logger.info("Signal %s empfangen - Skript wird beendet.", signum)
        _emergency_run_event.set()
        _shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    _logger.info("Luftanalyse gestartet (Intervall %ds).",
                 core_constants.ANALYSIS_INTERVAL_S)

    while True:
        try:
            run_one_analysis()
        except Exception as exc:
            _logger.error("Unerwarteter Fehler in der Analyse: %s",
                          exc, exc_info=True)

        _emergency_run_event.wait(timeout=core_constants.ANALYSIS_INTERVAL_S)
        _emergency_run_event.clear()


if __name__ == "__main__":
    sys.exit(main())
