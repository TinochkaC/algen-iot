"""
bridge_db_to_dashboard.py - Algen-IoT
=====================================

Aggregiert in regelmaessigen Abstaenden den aktuellen System-Zustand fuer
das Dashboard und speichert ihn als kompakten Einzeldatensatz in
MEASUREMENT_DASHBOARD_AGGREGATES (Bucket algen_system).

Aggregiert wird (Datenflussarchitektur Kapitel 3.7):
  - Aktuellste Sensorwerte (Reaktor + Raumnode)
  - Aktuellstes Analyse-Ergebnis (Luft + Algen)
  - Aktuelle Aktor-States
  - Anzahl unquittierter Alarme

Das Dashboard (Grafana o. ae.) liest aus diesem Measurement. Damit kann
das Frontend mit einer einzigen Query alles Wichtige darstellen.

Autor: Algen-IoT Team
Datum: 2026-05-31
"""

import signal
import sys
import time
from typing import Optional

from algen_iot_core import (
    core_constants,
    core_database,
    core_logger,
    core_mqtt,
    core_utils,
)


_logger = core_logger.get_logger(
    "bridge_db_to_dashboard",
    log_file_path=f"{core_constants.LOG_DIRECTORY_DEFAULT}/bridge_db_to_dashboard.log",
)


# =============================================================================
# AGGREGATIONS-FUNKTIONEN
# =============================================================================

def get_latest_sensor_values(measurement: str,
                              sensors: list[str]) -> dict:
    """Liefert die letzten Werte fuer eine Liste von Sensoren.

    Args:
        measurement: MEASUREMENT_REACTOR_SENSORS oder MEASUREMENT_ROOM_SENSORS.
        sensors:     Sensor-Namen, die abgefragt werden sollen.

    Returns:
        dict: {sensor_name: value, sensor_name_status: status}.
    """
    result: dict = {}
    for sensor_name in sensors:
        records = core_database.db_get_latest_sensors(sensor_name, limit=1)
        if records:
            result[sensor_name] = records[0].get("value")
        else:
            result[sensor_name] = None
    return result


def get_latest_analysis_summary(measurement: str) -> dict:
    """Liefert eine kompakte Zusammenfassung der letzten Analyse."""
    now_ts = core_utils.get_current_timestamp()
    records = core_database.db_get_records_by_timeframe(
        table_name=measurement,
        start_timestamp=now_ts - 2 * core_constants.ANALYSIS_INTERVAL_S,
        end_timestamp=now_ts + 60,
    )
    if not records:
        return {}

    by_timestamp: dict[int, dict] = {}
    for record in records:
        ts = record.get("timestamp")
        field = record.get("field")
        value = record.get("value")
        if ts is None or field is None:
            continue
        by_timestamp.setdefault(int(ts), {})[field] = value

    if not by_timestamp:
        return {}
    latest_ts = max(by_timestamp.keys())
    summary = dict(by_timestamp[latest_ts])
    summary["timestamp"] = latest_ts
    return summary


def get_active_actuator_states() -> dict:
    """Liefert den aktuellen state jedes Aktors."""
    states: dict = {}
    for actuator in core_constants.ACTUATORS:
        record = core_database.db_get_latest_record_by_condition(
            table_name=core_constants.MEASUREMENT_ACTUATOR_STATUS,
            condition_dict={"actuator": actuator},
        )
        states[f"{actuator}_state"] = record.get("state") if record else "unknown"
    return states


def get_unresolved_alarms_count() -> int:
    """Zaehlt die noch unquittierten Alarme."""
    now_ts = core_utils.get_current_timestamp()
    records = core_database.db_get_records_by_timeframe(
        table_name=core_constants.MEASUREMENT_ALARMS,
        start_timestamp=now_ts - 7 * 24 * 3600,  # letzte 7 Tage
        end_timestamp=now_ts,
        field_name="ui_status",
    )
    return sum(1 for r in records
               if r.get("value") == core_constants.UI_STATUS_UNRESOLVED)


# =============================================================================
# EIN AGGREGATIONS-ZYKLUS
# =============================================================================

def run_one_cycle() -> None:
    """Aggregiert die aktuellen Daten und schreibt einen Dashboard-Datensatz."""
    reactor_values = get_latest_sensor_values(
        core_constants.MEASUREMENT_REACTOR_SENSORS,
        core_constants.SENSORS_REACTOR,
    )
    room_values = get_latest_sensor_values(
        core_constants.MEASUREMENT_ROOM_SENSORS,
        core_constants.SENSORS_ROOM,
    )
    air_analysis = get_latest_analysis_summary(
        core_constants.MEASUREMENT_ANALYSIS_AIR
    )
    algae_analysis = get_latest_analysis_summary(
        core_constants.MEASUREMENT_ANALYSIS_ALGAE
    )
    actuator_states = get_active_actuator_states()
    unresolved_count = get_unresolved_alarms_count()

    payload = core_utils.build_standard_json(
        id_prefix=core_constants.UUID_PREFIX_DASHBOARD,
        parameters_dict={
            **reactor_values,
            **room_values,
            **actuator_states,
            "air_quality_index":     air_analysis.get("air_quality_index"),
            "action_recommendation": air_analysis.get("action_recommendation"),
            "vitality_score":        algae_analysis.get("vitality_score"),
            "growth_status":         algae_analysis.get("growth_status"),
            "unresolved_alarms":     unresolved_count,
        },
        id_field_name="dashboard_id",
    )

    success = core_database.db_insert_record(
        table_name=core_constants.MEASUREMENT_DASHBOARD_AGGREGATES,
        json_payload=payload,
    )
    if success:
        _logger.info("Dashboard-Aggregat geschrieben (alarms=%d).",
                     unresolved_count)
    else:
        _logger.error("Dashboard-Aggregat konnte NICHT gespeichert werden.")


# =============================================================================
# MAIN
# =============================================================================

def main() -> int:
    def _handle_signal(signum, _frame):
        _logger.info("Signal %s empfangen - Skript wird beendet.", signum)
        core_mqtt.mqtt_disconnect()
        core_database.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    _logger.info("Dashboard-Aggregator gestartet (Intervall %ds).",
                 core_constants.DASHBOARD_REFRESH_INTERVAL_S)

    while True:
        try:
            run_one_cycle()
        except Exception as exc:
            _logger.error("Unerwarteter Fehler im Zyklus: %s",
                          exc, exc_info=True)
        time.sleep(core_constants.DASHBOARD_REFRESH_INTERVAL_S)


if __name__ == "__main__":
    sys.exit(main())
