"""
core_hardware.py - Algen-IoT
============================

Zentrale Hardware-Abstraktionsschicht. Kapselt allen Zugriff auf Sensoren
(I2C, SPI, 1-Wire, ADC) und Aktoren (GPIO-Relais, PWM-LED) so, dass die
capture_*-, control_*- und analyze_*-Skripte hardware-unabhaengig bleiben.

Funktioniert auch ohne RPi.GPIO (Simulationsmodus), damit Skripte auf
Entwicklungs-Workstations getestet werden koennen.

Bezieht sich auf:
- Coding Guidelines, Kapitel 3 (core_hardware.py)
- Datenflussarchitektur und Datenstrukturen, Kapitel 3.1 + 4.1.3
- Pflichtenheft 7.1, Verkabelungs-Doku

Autor: Algen-IoT Team
Datum: 2026-05-31
"""

import json
import os
from typing import Optional

from algen_iot_core import core_constants
from algen_iot_core import core_logger


_logger = core_logger.get_logger("core_hardware")


# ============================================================================
# HARDWARE-ADAPTER (RPi.GPIO mit Fallback in Simulationsmodus)
# ============================================================================

try:
    import RPi.GPIO as _GPIO
    IS_SIMULATION_MODE = False
except (ImportError, RuntimeError):
    _GPIO = None
    IS_SIMULATION_MODE = True
    _logger.warning(
        "RPi.GPIO nicht verfuegbar - core_hardware laeuft im SIMULATIONSMODUS. "
        "Es werden keine physischen GPIOs geschaltet."
    )


_initialized_pins: dict[int, str] = {}
_pwm_instances: dict[int, object] = {}


def initialize_gpio() -> bool:
    """Initialisiert den GPIO-Subsystem (BCM-Modus, alle Aktor-Pins als OUT).

    Setzt alle Aktor-Pins (Heizung, Pumpe, LED) auf LOW als sicheren
    Startzustand. Wird im SIMULATIONSMODUS uebersprungen.

    Returns:
        bool: True bei Erfolg, False sonst.
    """
    if IS_SIMULATION_MODE:
        _logger.info("initialize_gpio() im Simulationsmodus uebersprungen.")
        return True
    try:
        _GPIO.setmode(_GPIO.BCM)
        _GPIO.setwarnings(False)
        for pin in (core_constants.GPIO_PIN_HEATER,
                    core_constants.GPIO_PIN_PUMP,
                    core_constants.GPIO_PIN_LED_PWM):
            _GPIO.setup(pin, _GPIO.OUT, initial=_GPIO.LOW)
            _initialized_pins[pin] = "OUT"
        # LED-PWM initialisieren
        pwm = _GPIO.PWM(core_constants.GPIO_PIN_LED_PWM,
                        core_constants.LED_PWM_FREQUENCY_HZ)
        pwm.start(0)
        _pwm_instances[core_constants.GPIO_PIN_LED_PWM] = pwm
        _logger.info("GPIO initialisiert (heater=%d, pump=%d, led=%d).",
                     core_constants.GPIO_PIN_HEATER,
                     core_constants.GPIO_PIN_PUMP,
                     core_constants.GPIO_PIN_LED_PWM)
        return True
    except Exception as exc:
        _logger.error("GPIO-Initialisierung fehlgeschlagen: %s", exc)
        return False


def cleanup_gpio() -> None:
    """Setzt alle GPIO-Pins zurueck (am Skriptende aufrufen)."""
    if IS_SIMULATION_MODE:
        return
    try:
        for pwm in _pwm_instances.values():
            pwm.stop()
        _pwm_instances.clear()
        _GPIO.cleanup()
        _initialized_pins.clear()
        _logger.info("GPIO aufgeraeumt.")
    except Exception as exc:
        _logger.error("GPIO-Cleanup-Fehler: %s", exc)


# ============================================================================
# 1. SENSORDATEN-AUSLESEN (Coding Guidelines core_hardware.py)
# ============================================================================

def get_sensor_data(sensor_name: str, bus_address: str | int) -> float:
    """Liest einen Sensor-Rohwert.

    Verbindet sich mit dem Sensor und liest analog oder digital aus.
    Bei Kommunikationsfehler wird SENSOR_ERROR_RETURN_VALUE (= -1.0)
    zurueckgegeben, NICHT geraised. Damit kann die aufrufende Schleife
    weiter laufen (Coding Guidelines Kapitel 5).

    HINWEIS: Diese Funktion ist hardware-spezifisch und muss pro Sensor
    eine konkrete Implementierung haben. Die hier eingebaute Logik ist
    ein Skeleton mit klar markierten Stellen fuer die echte Sensor-Lib
    (z. B. w1thermsensor fuer DS18B20, adafruit_ccs811 fuer CCS811,
    adafruit_dht fuer DHT11, spidev fuer MCP3008).

    Args:
        sensor_name: Einer aus SENSORS_REACTOR + SENSORS_ROOM.
        bus_address: I2C-Adresse (int), Pin-Nummer oder 1-Wire-ID (str).

    Returns:
        float: Sensor-Rohwert. -1.0 bei Fehler.
    """
    if sensor_name not in core_constants.IDEAL_VALUES_MAP:
        _logger.error("Unbekannter Sensorname: %s", sensor_name)
        return core_constants.SENSOR_ERROR_RETURN_VALUE

    if IS_SIMULATION_MODE:
        # Simulationsmodus liefert den Idealwert, damit Analyse-Skripte
        # gegen normal-Status testen koennen.
        simulated = core_constants.IDEAL_VALUES_MAP[sensor_name]
        _logger.debug("[SIM] %s @ %s -> %s", sensor_name, bus_address, simulated)
        return float(simulated)

    try:
        # ====================================================================
        # ECHTE HARDWARE-LOGIK -- pro Sensor implementieren!
        # Diese Stellen sind explizit als Hardware-spezifisch markiert.
        # ====================================================================
        if sensor_name == "water_temp":
            return _read_ds18b20(str(bus_address))
        if sensor_name in ("ph", "turbidity"):
            return _read_mcp3008_channel(int(bus_address))
        if sensor_name in ("co2", "voc"):
            return _read_ccs811(int(bus_address), sensor_name)
        if sensor_name in ("air_temp", "humidity"):
            return _read_dht11(int(bus_address), sensor_name)
        if sensor_name == "light_intensity":
            return _read_lux_sensor(int(bus_address))
        # ====================================================================
        _logger.error("Kein Reader fuer Sensor '%s' implementiert.", sensor_name)
        return core_constants.SENSOR_ERROR_RETURN_VALUE
    except Exception as exc:
        _logger.error("Sensor-Read-Fehler [%s @ %s]: %s",
                       sensor_name, bus_address, exc)
        return core_constants.SENSOR_ERROR_RETURN_VALUE


def _read_ds18b20(device_id: str) -> float:
    """1-Wire DS18B20. Echte Implementierung verwendet w1thermsensor.

    DS18B20-Defekt-Indikatoren: -127.0 (Verbindung weg) oder 85.0
    (Power-On-Reset). Diese werden von validate_sensor_data() abgefangen.
    """
    # Beispiel echte Implementierung (vorerst auskommentiert):
    # from w1thermsensor import W1ThermSensor
    # return W1ThermSensor(sensor_id=device_id).get_temperature()
    raise NotImplementedError("DS18B20-Reader noch nicht installiert.")


def _read_mcp3008_channel(channel: int) -> float:
    """SPI-ADC MCP3008. Liefert ADC-Rohwert 0..1023 (10-Bit)."""
    # from gpiozero import MCP3008
    # adc = MCP3008(channel=channel)
    # return adc.value * core_constants.SENSOR_ADC_MAX_VALUE_10BIT
    raise NotImplementedError("MCP3008-Reader noch nicht installiert.")


def _read_ccs811(i2c_address: int, measurement: str) -> float:
    """I2C-CCS811 (eCO2 + TVOC)."""
    # import board, busio, adafruit_ccs811
    # i2c = busio.I2C(board.SCL, board.SDA)
    # ccs = adafruit_ccs811.CCS811(i2c, address=i2c_address)
    # return ccs.eco2 if measurement == "co2" else ccs.tvoc
    raise NotImplementedError("CCS811-Reader noch nicht installiert.")


def _read_dht11(gpio_pin: int, measurement: str) -> float:
    """1-Wire-DHT11 (Lufttemperatur + Luftfeuchte)."""
    # import adafruit_dht, board
    # dht = adafruit_dht.DHT11(getattr(board, f"D{gpio_pin}"))
    # return dht.temperature if measurement == "air_temp" else dht.humidity
    raise NotImplementedError("DHT11-Reader noch nicht installiert.")


def _read_lux_sensor(i2c_address: int) -> float:
    """Platzhalter Lux-Sensor (Hardware projektweit noch ungeklaert)."""
    raise NotImplementedError(
        "Kein Lux-Sensor in Beschaffung -- siehe Projektklaerung."
    )


# ============================================================================
# 2. VALIDIERUNG (Datenflussarch. 4.1.3.A/B/C)
# ============================================================================

def validate_sensor_data(sensor_name: str, physical_value: float) -> str:
    """Bewertet einen physikalischen Sensorwert anhand der Grenzwerte.

    Implementiert die Validierungslogik aus Datenflussarch. 4.1.3
    inklusive der Hardware-Fehler-Indikatoren (DS18B20 -127/85, ADC 0/1023).

    Args:
        sensor_name: Einer aus SENSORS_REACTOR + SENSORS_ROOM.
        physical_value: Bereits in Einheit umgerechneter Wert (°C, pH, ppm,...).

    Returns:
        str: Ein Wert aus DATA_STATUS_VALID_VALUES.
    """
    # 1) Sensor-Defekt-Indikatoren zuerst
    if physical_value == core_constants.SENSOR_ERROR_RETURN_VALUE:
        return core_constants.DATA_STATUS_SENSOR_ERROR

    if sensor_name == "water_temp":
        if physical_value in core_constants.SENSOR_VALUES_DS18B20_DEFECT:
            return core_constants.DATA_STATUS_SENSOR_ERROR

    thresholds = core_constants.THRESHOLD_VALUES_MAP.get(sensor_name)
    if not thresholds:
        _logger.error("Keine Schwellwerte fuer Sensor '%s'.", sensor_name)
        return core_constants.DATA_STATUS_SENSOR_ERROR

    # 2) sensor_error-Range (sehr breit -> physikalisch unmoeglich)
    sensor_error_range = thresholds.get("sensor_error_range")
    if sensor_error_range:
        if not (sensor_error_range["min"] <= physical_value <= sensor_error_range["max"]):
            return core_constants.DATA_STATUS_SENSOR_ERROR

    sensor_error_low = thresholds.get("sensor_error_low")
    if sensor_error_low and physical_value < sensor_error_low["max"]:
        return core_constants.DATA_STATUS_SENSOR_ERROR

    sensor_error_high = thresholds.get("sensor_error_high")
    if sensor_error_high and physical_value > sensor_error_high["min"]:
        return core_constants.DATA_STATUS_SENSOR_ERROR

    # 3) normal-Bereich
    normal = thresholds["normal"]
    if normal["min"] <= physical_value <= normal["max"]:
        return core_constants.DATA_STATUS_NORMAL

    # 4) warning-Bereiche
    for warning_key in ("warning_low", "warning_high", "warning"):
        warning = thresholds.get(warning_key)
        if warning and warning["min"] <= physical_value <= warning["max"]:
            return core_constants.DATA_STATUS_WARNING

    # 5) Alles andere ist error
    return core_constants.DATA_STATUS_ERROR


# ============================================================================
# 3. KONFIGURATIONSDATEIEN (Coding Guidelines core_hardware.py)
# ============================================================================

def read_configuration_file(config_path: str) -> dict:
    """Laedt eine sensorspezifische JSON-Konfigurationsdatei.

    Beispielinhalt (siehe config/sensor_ph.json):
        {
            "sensor_name": "ph",
            "bus_type": "spi-adc",
            "bus_address": 0,
            "calibration_factor": 3.5,
            "calibration_offset": 0.7
        }

    Args:
        config_path: Absoluter Pfad (i. d. R. aus CONFIGURATION_FILE_PATH_*).

    Returns:
        dict: Geparster Inhalt der Konfigurationsdatei.
        Bei Fehlern wird ein leeres dict {} zurueckgegeben und ein
        ERROR-Log geschrieben (kein raise, damit das Skript weiterlaufen kann).
    """
    try:
        if not os.path.exists(config_path):
            _logger.error("Konfigurationsdatei nicht gefunden: %s", config_path)
            return {}
        with open(config_path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        _logger.error("Konfigurationsdatei %s nicht lesbar: %s",
                       config_path, exc)
        return {}


# ============================================================================
# 4. SENSOR-STROMVERSORGUNG (Coding Guidelines core_hardware.py)
# ============================================================================

def turn_sensor_on(sensor_name: str, power_pin: int) -> bool:
    """Setzt den Stromversorgungspin eines Sensors auf HIGH.

    Wird beim Skriptstart oder nach einer Notabschaltung aufgerufen,
    um den Sensor aufzuwecken.

    Args:
        sensor_name: Name fuer das Log.
        power_pin: BCM-GPIO-Pin der Stromversorgung.

    Returns:
        bool: True, wenn der Pin erfolgreich gesetzt wurde.
    """
    if IS_SIMULATION_MODE:
        _logger.info("[SIM] turn_sensor_on(%s, pin=%d).", sensor_name, power_pin)
        return True
    try:
        _GPIO.setup(power_pin, _GPIO.OUT)
        _GPIO.output(power_pin, _GPIO.HIGH)
        _logger.info("Sensor '%s' eingeschaltet (pin=%d).", sensor_name, power_pin)
        return True
    except Exception as exc:
        _logger.error("turn_sensor_on(%s) fehlgeschlagen: %s", sensor_name, exc)
        return False


def turn_sensor_off(sensor_name: str, power_pin: int) -> bool:
    """Setzt den Stromversorgungspin eines Sensors auf LOW.

    Wird bei der Notabschaltung verwendet, um defekte Sensoren physisch
    vom Strom zu trennen (Kurzschlussschutz, Datenflussarch. 3.1.1).

    Args:
        sensor_name: Name fuer das Log.
        power_pin: BCM-GPIO-Pin der Stromversorgung.

    Returns:
        bool: True bei Erfolg.
    """
    if IS_SIMULATION_MODE:
        _logger.info("[SIM] turn_sensor_off(%s, pin=%d).", sensor_name, power_pin)
        return True
    try:
        _GPIO.setup(power_pin, _GPIO.OUT)
        _GPIO.output(power_pin, _GPIO.LOW)
        _logger.info("Sensor '%s' ausgeschaltet (pin=%d).", sensor_name, power_pin)
        return True
    except Exception as exc:
        _logger.error("turn_sensor_off(%s) fehlgeschlagen: %s", sensor_name, exc)
        return False


# ============================================================================
# 5. AKTOR-STEUERUNG (Coding Guidelines erweiterte Funktionen)
# ============================================================================

def set_actuator_pin(pin_id: int, is_high: bool) -> bool:
    """Schaltet einen Relais-Pin (Pumpe / Heizung).

    Kapselt Hardware-Exceptions zentral ab (Kurzschluss, Treiber-Fehler).

    Args:
        pin_id: BCM-GPIO-Pin (siehe GPIO_PIN_HEATER, GPIO_PIN_PUMP).
        is_high: True = Relais zieht an (HIGH), False = LOW.

    Returns:
        bool: True bei Erfolg, False bei Exception.
    """
    if IS_SIMULATION_MODE:
        _logger.info("[SIM] set_actuator_pin(%d, %s).", pin_id, is_high)
        return True
    try:
        if pin_id not in _initialized_pins:
            _GPIO.setup(pin_id, _GPIO.OUT)
            _initialized_pins[pin_id] = "OUT"
        _GPIO.output(pin_id, _GPIO.HIGH if is_high else _GPIO.LOW)
        return True
    except Exception as exc:
        _logger.error("set_actuator_pin(%d) fehlgeschlagen: %s", pin_id, exc)
        return False


def set_pwm_duty_cycle(pin_id: int, duty_cycle: int) -> bool:
    """Setzt den PWM-Duty-Cycle fuer den LED-Treiber.

    Kapselt die Hardware-Steuerung des PWM-Controllers (Datenflussarch. 4.4
    LED: "PWM-Duty-Cycle auf X%"). Wandelt prozentuale Anforderung in das
    Hardware-Signal um.

    Args:
        pin_id: BCM-Pin (i. d. R. GPIO_PIN_LED_PWM = 18).
        duty_cycle: 0-100 (Prozent). Werte ausserhalb werden geclampt.

    Returns:
        bool: True bei Erfolg.
    """
    safe_duty = max(core_constants.LED_INTENSITY_MIN_PCT,
                    min(core_constants.LED_INTENSITY_MAX_PCT, duty_cycle))
    if IS_SIMULATION_MODE:
        _logger.info("[SIM] set_pwm_duty_cycle(%d, %d%%).", pin_id, safe_duty)
        return True
    try:
        pwm = _pwm_instances.get(pin_id)
        if pwm is None:
            _logger.error("Kein PWM-Kanal initialisiert fuer pin=%d.", pin_id)
            return False
        pwm.ChangeDutyCycle(safe_duty)
        return True
    except Exception as exc:
        _logger.error("set_pwm_duty_cycle(%d) fehlgeschlagen: %s", pin_id, exc)
        return False
