"""
example_capture_room_climate.py - Algen-IoT REFERENZ-SKRIPT
==========================================================

Demonstriert, wie ein Skript die core-Bibliothek nutzt. Dient als
Vorlage fuer alle echten capture_/analyze_/control_/bridge_-Skripte.

Bezieht sich auf:
- Datenflussarchitektur und Datenstrukturen, Kapitel 3.1 (Sensoren -> DB)

Autor: Algen-IoT Team
Datum: 2026-05-31
"""

import signal
import sys
import time

from core import core_constants
from core import core_database
from core import core_hardware
from core import core_logger
from core import core_math
from core import core_mqtt
from core import core_utils


_logger = core_logger.get_logger(
    "capture_room_climate",
    log_file_path=f"{core_constants.LOG_DIRECTORY_DEFAULT}/capture_room_climate.log",
)


# =========================================================================
# SENSOR-INITIALISIERUNG
# =========================================================================

def initialize_sensors() -> list[str]:
    """Startet alle Raumluft-Sensoren sequenziell.

    Returns:
        list[str]: Liste der erfolgreich aktiven Sensoren.
    """
    active_sensors: list[str] = []
    for sensor_name in core_constants.SENSORS_ROOM:
        config_path = core_constants.CONFIGURATION_FILE_PATH_MAP[sensor_name]
        config = core_hardware.read_configuration_file(config_path)
        if not config:
            _logger.error("Sensor '%s' uebersprungen (keine Konfiguration).",
                          sensor_name)
            continue
        power_pin = config.get("power_pin")
        if power_pin:
            core_hardware.turn_sensor_on(sensor_name, int(power_pin))
        active_sensors.append(sensor_name)
    _logger.info("Aktive Sensoren: %s", active_sensors)
    return active_sensors


# =========================================================================
# HAUPT-SCHLEIFE
# =========================================================================

def read_and_publish_once(active_sensors: list[str]) -> None:
    """Ein Lese- und Speicherdurchgang.

    Folgt exakt dem Workflow aus Datenflussarchitektur 3.1.1:
        Abfrage -> Umwandlung -> Validierung -> Alarm -> Verpackung -> DB.
    """
    payload_fields: dict = {"device_id": core_constants.ROOMNODE_DEVICE_ID}
    has_any_alarm = False

    for sensor_name in active_sensors:
        config_path = core_constants.CONFIGURATION_FILE_PATH_MAP[sensor_name]
        config = core_hardware.read_configuration_file(config_path)
        bus_address = config.get("bus_address", 0)
        unit = config.get("unit", "")

        # Schritt 1: Rohwert lesen (mit MAX_RETRIES)
        raw_value = core_constants.SENSOR_ERROR_RETURN_VALUE
        for attempt in range(1, core_constants.MAX_RETRIES + 1):
            raw_value = core_hardware.get_sensor_data(sensor_name, bus_address)
            if raw_value != core_constants.SENSOR_ERROR_RETURN_VALUE:
                break
            _logger.warning("Sensor '%s' Versuch %d/%d fehlgeschlagen.",
                            sensor_name, attempt, core_constants.MAX_RETRIES)
            time.sleep(0.5)

        # Schritt 2: Validierung
        data_status = core_hardware.validate_sensor_data(sensor_name, raw_value)
        payload_fields[sensor_name] = raw_value
        payload_fields[f"{sensor_name}_status"] = data_status

        # Schritt 3: Alarm bei nicht-normalem Status
        if data_status != core_constants.DATA_STATUS_NORMAL:
            has_any_alarm = True
            alarm_payload = core_utils.build_standard_json(
                id_prefix=core_constants.UUID_PREFIX_ALARM,
                parameters_dict={
                    "device_id":     core_constants.ROOMNODE_DEVICE_ID,
                    "sensor_name":   sensor_name,
                    "current_value": raw_value,
                    "status":        data_status,
                    "unit":          unit,
                },
                id_field_name="alarm_id",
            )
            core_mqtt.mqtt_publish_alarm(
                device_name=core_constants.ROOMNODE_DEVICE_ID,
                component_type="sensor",
                component_name=sensor_name,
                json_payload=alarm_payload,
            )

        # Sonderfall sensor_error: Sensor abschalten (Kurzschlussschutz)
        if data_status == core_constants.DATA_STATUS_SENSOR_ERROR:
            power_pin = config.get("power_pin")
            if power_pin:
                core_hardware.turn_sensor_off(sensor_name, int(power_pin))

    # Schritt 4: Standard-JSON bauen und in DB schreiben
    payload = core_utils.build_standard_json(
        id_prefix=core_constants.UUID_PREFIX_SENSOR_RECORD,
        parameters_dict=payload_fields,
        id_field_name="record_id",
    )
    core_database.db_insert_record(
        table_name=core_constants.MEASUREMENT_ROOM_SENSORS,
        json_payload=payload,
    )
    _logger.info("Sensorzyklus abgeschlossen (alarm=%s).", has_any_alarm)


def main() -> int:
    """Endlosschleife: alle READ_INTERVAL_AIR_S Sekunden."""
    if not core_hardware.initialize_gpio():
        _logger.error("GPIO-Initialisierung fehlgeschlagen - Abbruch.")
        return 1

    def shutdown(signum, frame):
        _logger.info("Signal %s empfangen - beende sauber.", signum)
        core_hardware.cleanup_gpio()
        core_mqtt.mqtt_disconnect()
        core_database.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    active_sensors = initialize_sensors()

    while True:
        try:
            read_and_publish_once(active_sensors)
        except Exception as exc:
            # Coding Guidelines Kapitel 5: Endlosschleife darf nie abstuerzen.
            _logger.error("Unerwarteter Fehler im Zyklus: %s", exc)
        time.sleep(core_constants.READ_INTERVAL_AIR_S)


if __name__ == "__main__":
    sys.exit(main())
