"""
capture_reactor_sensors.py - Algen-IoT
======================================

Periodische Erfassung der Reaktor-Sensoren (water_temp, ph, turbidity,
light_intensity) alle 30 Sekunden. Schreibt jeden Messzyklus in den
algen_bio-Bucket der InfluxDB und publiziert Alarme via MQTT, wenn ein
Sensor nicht im normal-Bereich liegt.

Realisiert Datenflussarchitektur Kapitel 3.1.1.

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
    core_hardware,
    core_logger,
    core_mqtt,
    core_utils,
)


_logger = core_logger.get_logger(
    "capture_reactor_sensors",
    log_file_path=f"{core_constants.LOG_DIRECTORY_DEFAULT}/capture_reactor_sensors.log",
)


# =============================================================================
# SENSOR-INITIALISIERUNG
# =============================================================================

def initialize_active_sensors() -> dict[str, dict]:
    """Laedt die Konfigurationen aller Reaktor-Sensoren und schaltet sie ein.

    Returns:
        dict[str, dict]: Mapping sensor_name -> Konfigurations-Dict.
            Sensoren ohne ladbare Konfiguration werden uebersprungen.
    """
    active_sensors: dict[str, dict] = {}
    for sensor_name in core_constants.SENSORS_REACTOR:
        config_path = core_constants.CONFIGURATION_FILE_PATH_MAP.get(sensor_name)
        if not config_path:
            _logger.error("Kein Konfigurationspfad fuer Sensor '%s'.", sensor_name)
            continue

        config = core_hardware.read_configuration_file(config_path)
        if not config:
            _logger.error("Sensor '%s' wird uebersprungen (Konfiguration fehlt).",
                          sensor_name)
            continue

        power_pin = config.get("power_pin")
        if power_pin is not None:
            core_hardware.turn_sensor_on(sensor_name, int(power_pin))

        active_sensors[sensor_name] = config

    _logger.info("Aktive Reaktor-Sensoren: %s", sorted(active_sensors.keys()))
    return active_sensors


# =============================================================================
# EIN MESSZYKLUS
# =============================================================================

def read_one_sensor(sensor_name: str, config: dict) -> tuple[float, str]:
    """Liest einen Sensor mit Retry-Logik und validiert den Wert.

    Args:
        sensor_name: Einer aus SENSORS_REACTOR.
        config: Sensorspezifische Konfiguration aus read_configuration_file.

    Returns:
        tuple[float, str]: (physikalischer Wert, data_status).
            Bei sensor_error wird der Sensor zusaetzlich abgeschaltet.
    """
    bus_address = config.get("bus_address", 0)
    raw_value = core_constants.SENSOR_ERROR_RETURN_VALUE

    for attempt in range(1, core_constants.MAX_RETRIES + 1):
        raw_value = core_hardware.get_sensor_data(sensor_name, bus_address)
        if raw_value != core_constants.SENSOR_ERROR_RETURN_VALUE:
            break
        _logger.warning("Sensor '%s' Leseversuch %d/%d fehlgeschlagen.",
                        sensor_name, attempt, core_constants.MAX_RETRIES)
        time.sleep(0.5)

    data_status = core_hardware.validate_sensor_data(sensor_name, raw_value)

    # Bei sensor_error: Stromversorgung kappen (Kurzschluss-Schutz)
    if data_status == core_constants.DATA_STATUS_SENSOR_ERROR:
        power_pin = config.get("power_pin")
        if power_pin is not None:
            core_hardware.turn_sensor_off(sensor_name, int(power_pin))

    return raw_value, data_status


def publish_sensor_alarm(sensor_name: str,
                          current_value: float,
                          data_status: str,
                          unit: str) -> None:
    """Publiziert einen Sensor-Alarm auf das spec-konforme Topic.

    Args:
        sensor_name: Einer aus SENSORS_REACTOR.
        current_value: Der ausreissende Messwert.
        data_status: warning, error oder sensor_error.
        unit: Einheit des Werts (z. B. "C", "pH", "g/l").
    """
    alarm_payload = core_utils.build_standard_json(
        id_prefix=core_constants.UUID_PREFIX_ALARM,
        parameters_dict={
            "device_id":      core_constants.REACTOR_DEVICE_ID,
            "sensor_name":    sensor_name,
            "current_value":  current_value,
            "status":         data_status,
            "unit":           unit,
            "alert_level":    _map_status_to_alert_level(data_status),
            "is_critical":    data_status in (
                core_constants.DATA_STATUS_ERROR,
                core_constants.DATA_STATUS_SENSOR_ERROR,
            ),
        },
        id_field_name="alarm_id",
    )
    core_mqtt.mqtt_publish_alarm(
        device_name=core_constants.REACTOR_DEVICE_ID,
        component_type="sensor",
        component_name=sensor_name,
        json_payload=alarm_payload,
    )


def _map_status_to_alert_level(data_status: str) -> str:
    """Bildet data_status auf alert_level ab (Datenflussarch. 4.6)."""
    if data_status == core_constants.DATA_STATUS_WARNING:
        return core_constants.ALERT_LEVEL_WARNING
    if data_status in (core_constants.DATA_STATUS_ERROR,
                       core_constants.DATA_STATUS_SENSOR_ERROR):
        return core_constants.ALERT_LEVEL_CRITICAL
    return core_constants.ALERT_LEVEL_INFO


def run_one_cycle(active_sensors: dict[str, dict]) -> None:
    """Ein vollstaendiger Mess- und Speicherzyklus.

    Args:
        active_sensors: Mapping aus initialize_active_sensors().
    """
    record_fields: dict = {"device_id": core_constants.REACTOR_DEVICE_ID}

    for sensor_name, config in active_sensors.items():
        value, status = read_one_sensor(sensor_name, config)

        record_fields[sensor_name] = value
        record_fields[f"{sensor_name}_status"] = status

        if status != core_constants.DATA_STATUS_NORMAL:
            publish_sensor_alarm(
                sensor_name=sensor_name,
                current_value=value,
                data_status=status,
                unit=config.get("unit", ""),
            )

    payload = core_utils.build_standard_json(
        id_prefix=core_constants.UUID_PREFIX_SENSOR_RECORD,
        parameters_dict=record_fields,
        id_field_name="record_id",
    )
    success = core_database.db_insert_record(
        table_name=core_constants.MEASUREMENT_REACTOR_SENSORS,
        json_payload=payload,
    )
    if success:
        _logger.info("Reaktor-Sensorzyklus gespeichert (%d Sensoren).",
                     len(active_sensors))
    else:
        _logger.error("Reaktor-Sensorzyklus konnte NICHT gespeichert werden.")


# =============================================================================
# MAIN
# =============================================================================

def _shutdown(active_sensors: dict[str, dict]) -> None:
    """Sauberes Herunterfahren: Sensoren stromlos, GPIO/MQTT/DB schliessen."""
    for sensor_name, config in active_sensors.items():
        power_pin = config.get("power_pin")
        if power_pin is not None:
            core_hardware.turn_sensor_off(sensor_name, int(power_pin))
    core_hardware.cleanup_gpio()
    core_mqtt.mqtt_disconnect()
    core_database.close()


def main() -> int:
    """Endlosschleife: alle READ_INTERVAL_REAKTOR_S Sekunden ein Zyklus.

    Returns:
        int: 0 bei normalem Beenden, 1 bei Init-Fehler.
    """
    if not core_hardware.initialize_gpio():
        _logger.error("GPIO-Initialisierung fehlgeschlagen - Abbruch.")
        return 1

    active_sensors = initialize_active_sensors()
    if not active_sensors:
        _logger.error("Kein Reaktor-Sensor aktiv - Abbruch.")
        return 1

    def _handle_signal(signum, _frame):
        _logger.info("Signal %s empfangen - Skript wird beendet.", signum)
        _shutdown(active_sensors)
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    _logger.info("Reaktor-Sensorerfassung gestartet (Intervall %ds).",
                 core_constants.READ_INTERVAL_REAKTOR_S)

    while True:
        try:
            run_one_cycle(active_sensors)
        except Exception as exc:
            # Zentrale Absicherung gegen unerwartete Fehler:
            # die Schleife darf NICHT abstuerzen (Coding Guidelines Kap. 5).
            _logger.error("Unerwarteter Fehler im Zyklus: %s", exc, exc_info=True)
        time.sleep(core_constants.READ_INTERVAL_REAKTOR_S)


if __name__ == "__main__":
    sys.exit(main())
