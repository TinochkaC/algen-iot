"""
capture_hardware_actuators.py - Algen-IoT
=========================================

Empfaengt Aktor-Befehle ueber MQTT (Topic: pbr/reactor-01/actuator/+/cmd)
und steuert die GPIO-Ausgaenge des Raspberry Pi:
- heater (Relais an GPIO 27)
- pump   (Relais an GPIO 17, zeitgesteuerte Aktion)
- led    (PWM an GPIO 18)

Meldet jeden State (accepted -> running -> completed/error) auf dem
zugehoerigen status-Topic zurueck. Bei Hardware-Fehlern wird zusaetzlich
ein Alarm auf pbr/reactor-01/alarm/actuator/<actuator> publiziert.

Realisiert Datenflussarchitektur Kapitel 3.4.

Autor: Algen-IoT Team
Datum: 2026-05-31
"""

import signal
import sys
import threading
import time

from algen_iot_core import (
    core_constants,
    core_hardware,
    core_logger,
    core_mqtt,
    core_utils,
)


_logger = core_logger.get_logger(
    "capture_hardware_actuators",
    log_file_path=f"{core_constants.LOG_DIRECTORY_DEFAULT}/capture_hardware_actuators.log",
)


# =============================================================================
# STATE: AKTIVE PUMPEN-AKTIONEN
# =============================================================================
# Dient zum sauberen Abbrechen einer laufenden Pumpe bei Notabschaltung.
_active_pump_events: dict[str, threading.Event] = {}


# =============================================================================
# STATUS-RUECKMELDUNG
# =============================================================================

def publish_status(actuator: str,
                   action_id: str,
                   state: str,
                   error_details: str = "",
                   error_code: str = "") -> None:
    """Publiziert eine Aktor-Rueckmeldung gemaess Datenflussarch. 4.4.

    Args:
        actuator:        Einer aus core_constants.ACTUATORS.
        action_id:       Die UUID des Befehls (uebernommen aus dem CMD).
        state:           accepted | running | completed | error | timeout.
        error_details:   Klartext-Beschreibung, nur bei state=error.
        error_code:      hardware_fault | timeout_exceeded | invalid_command.
    """
    if state not in core_constants.ACTUATOR_STATE_VALID_VALUES:
        _logger.error("Versuchter Publish mit ungueltigem state '%s'.", state)
        return

    parameters: dict = {
        "action_id":     action_id,
        "actuator":      actuator,
        "state":         state,
    }
    if state == core_constants.ACTUATOR_STATE_ERROR:
        parameters["error_details"] = error_details
        if error_code:
            parameters["error_code"] = error_code

    payload = core_utils.build_standard_json(
        id_prefix="",  # ID ist schon gesetzt (action_id), Prefix nicht noetig
        parameters_dict=parameters,
        id_field_name="action_id",
    )
    core_mqtt.mqtt_publish_status(actuator_name=actuator, json_payload=payload)


def publish_hardware_alarm(actuator: str,
                            action_id: str,
                            error_code: str,
                            error_details: str) -> None:
    """Publiziert einen Aktor-Alarm bei Hardware-Fehler."""
    alarm_payload = core_utils.build_standard_json(
        id_prefix=core_constants.UUID_PREFIX_ALARM,
        parameters_dict={
            "actuator":     actuator,
            "action_id":    action_id,
            "error_code":   error_code,
            "error_details": error_details,
            "alert_level":  core_constants.ALERT_LEVEL_CRITICAL,
            "is_critical":  True,
        },
        id_field_name="alarm_id",
    )
    core_mqtt.mqtt_publish_alarm(
        device_name=core_constants.REACTOR_DEVICE_ID,
        component_type="actuator",
        component_name=actuator,
        json_payload=alarm_payload,
    )


# =============================================================================
# AKTOR-HANDLER (einer pro Aktor)
# =============================================================================

def handle_heater(action_id: str, payload: dict) -> None:
    """Steuert das Heizungs-Relais an GPIO 27.

    Args:
        action_id: UUID des Befehls.
        payload:   Spec-konformes JSON mit is_enabled, is_action_on,
                   target_water_temp (optional, fuer Logging/Diagnose).
    """
    is_enabled = bool(payload.get("is_enabled", False))
    is_action_on = bool(payload.get("is_action_on", False))

    publish_status(core_constants.ACTUATOR_HEATER, action_id,
                   core_constants.ACTUATOR_STATE_RUNNING)

    should_be_on = is_enabled and is_action_on
    success = core_hardware.set_actuator_pin(
        pin_id=core_constants.GPIO_PIN_HEATER,
        is_high=should_be_on,
    )
    if success:
        publish_status(core_constants.ACTUATOR_HEATER, action_id,
                       core_constants.ACTUATOR_STATE_COMPLETED)
        _logger.info("Heater action_id=%s -> %s.", action_id,
                     "ON" if should_be_on else "OFF")
    else:
        publish_status(core_constants.ACTUATOR_HEATER, action_id,
                       core_constants.ACTUATOR_STATE_ERROR,
                       error_details="GPIO-Schaltung fehlgeschlagen",
                       error_code=core_constants.ERROR_CODE_HARDWARE_FAULT)
        publish_hardware_alarm(core_constants.ACTUATOR_HEATER, action_id,
                                core_constants.ERROR_CODE_HARDWARE_FAULT,
                                "Heizungs-Relais nicht schaltbar")


def _pump_cycle(action_id: str, duration_s: int) -> None:
    """Fuehrt eine Pumpen-Dosierung aus (laeuft im Daemon-Thread).

    Pumpe wird eingeschaltet, dann duration_s Sekunden gewartet (mit
    Cancel-Moeglichkeit via threading.Event), anschliessend wieder
    ausgeschaltet.
    """
    cancel_event = threading.Event()
    _active_pump_events[action_id] = cancel_event

    try:
        # Pumpe einschalten
        if not core_hardware.set_actuator_pin(
                pin_id=core_constants.GPIO_PIN_PUMP, is_high=True):
            publish_status(core_constants.ACTUATOR_PUMP, action_id,
                           core_constants.ACTUATOR_STATE_ERROR,
                           error_details="Pumpen-Relais lasst sich nicht einschalten",
                           error_code=core_constants.ERROR_CODE_HARDWARE_FAULT)
            publish_hardware_alarm(core_constants.ACTUATOR_PUMP, action_id,
                                    core_constants.ERROR_CODE_HARDWARE_FAULT,
                                    "Pumpen-Relais nicht schaltbar")
            return

        publish_status(core_constants.ACTUATOR_PUMP, action_id,
                       core_constants.ACTUATOR_STATE_RUNNING)
        _logger.info("Pumpe action_id=%s gestartet (%ds).", action_id, duration_s)

        # Warten mit Abbruch-Moeglichkeit
        was_cancelled = cancel_event.wait(timeout=duration_s)

        # Pumpe ausschalten
        core_hardware.set_actuator_pin(
            pin_id=core_constants.GPIO_PIN_PUMP, is_high=False)

        if was_cancelled:
            publish_status(core_constants.ACTUATOR_PUMP, action_id,
                           core_constants.ACTUATOR_STATE_ERROR,
                           error_details="Pumpenzyklus durch Notabschaltung beendet",
                           error_code=core_constants.ERROR_CODE_HARDWARE_FAULT)
        else:
            publish_status(core_constants.ACTUATOR_PUMP, action_id,
                           core_constants.ACTUATOR_STATE_COMPLETED)
            _logger.info("Pumpe action_id=%s abgeschlossen.", action_id)
    finally:
        _active_pump_events.pop(action_id, None)


def handle_pump(action_id: str, payload: dict) -> None:
    """Startet eine zeitgesteuerte Pumpen-Dosierung im Hintergrund-Thread."""
    is_enabled = bool(payload.get("is_enabled", False))
    is_action_on = bool(payload.get("is_action_on", False))

    # Wenn Pumpe deaktiviert oder ausgeschaltet werden soll -> sofort aus
    if not is_enabled or not is_action_on:
        core_hardware.set_actuator_pin(
            pin_id=core_constants.GPIO_PIN_PUMP, is_high=False)
        # Eventuell laufende Pumpe abbrechen
        for active_id, event in list(_active_pump_events.items()):
            event.set()
            _logger.info("Pumpe action_id=%s vorzeitig abgebrochen.", active_id)
        publish_status(core_constants.ACTUATOR_PUMP, action_id,
                       core_constants.ACTUATOR_STATE_COMPLETED)
        return

    # Dauer validieren
    try:
        duration_s = int(payload.get("duration_s", 0))
    except (TypeError, ValueError):
        publish_status(core_constants.ACTUATOR_PUMP, action_id,
                       core_constants.ACTUATOR_STATE_ERROR,
                       error_details="duration_s muss eine Ganzzahl sein",
                       error_code=core_constants.ERROR_CODE_INVALID_COMMAND)
        return

    if not (core_constants.PUMP_DURATION_MIN_S
            <= duration_s
            <= core_constants.PUMP_DURATION_MAX_S):
        publish_status(core_constants.ACTUATOR_PUMP, action_id,
                       core_constants.ACTUATOR_STATE_ERROR,
                       error_details=f"duration_s {duration_s} ausserhalb "
                                     f"[{core_constants.PUMP_DURATION_MIN_S}, "
                                     f"{core_constants.PUMP_DURATION_MAX_S}]",
                       error_code=core_constants.ERROR_CODE_INVALID_COMMAND)
        return

    publish_status(core_constants.ACTUATOR_PUMP, action_id,
                   core_constants.ACTUATOR_STATE_ACCEPTED)

    threading.Thread(
        target=_pump_cycle,
        args=(action_id, duration_s),
        daemon=True,
    ).start()


def handle_led(action_id: str, payload: dict) -> None:
    """Setzt den PWM-Duty-Cycle des LED-Treibers an GPIO 18."""
    is_enabled = bool(payload.get("is_enabled", False))
    is_action_on = bool(payload.get("is_action_on", False))

    publish_status(core_constants.ACTUATOR_LED, action_id,
                   core_constants.ACTUATOR_STATE_RUNNING)

    if not is_enabled or not is_action_on:
        target_pct = 0
    else:
        try:
            target_pct = int(payload.get("target_intensity", 0))
        except (TypeError, ValueError):
            publish_status(core_constants.ACTUATOR_LED, action_id,
                           core_constants.ACTUATOR_STATE_ERROR,
                           error_details="target_intensity muss eine Ganzzahl sein",
                           error_code=core_constants.ERROR_CODE_INVALID_COMMAND)
            return

    target_pct = int(core_utils.clamp(
        target_pct,
        core_constants.LED_INTENSITY_MIN_PCT,
        core_constants.LED_INTENSITY_MAX_PCT,
    ))

    success = core_hardware.set_pwm_duty_cycle(
        pin_id=core_constants.GPIO_PIN_LED_PWM,
        duty_cycle=target_pct,
    )
    if success:
        publish_status(core_constants.ACTUATOR_LED, action_id,
                       core_constants.ACTUATOR_STATE_COMPLETED)
        _logger.info("LED action_id=%s -> %d%%.", action_id, target_pct)
    else:
        publish_status(core_constants.ACTUATOR_LED, action_id,
                       core_constants.ACTUATOR_STATE_ERROR,
                       error_details="LED-PWM-Schaltung fehlgeschlagen",
                       error_code=core_constants.ERROR_CODE_HARDWARE_FAULT)
        publish_hardware_alarm(core_constants.ACTUATOR_LED, action_id,
                                core_constants.ERROR_CODE_HARDWARE_FAULT,
                                "LED-PWM nicht steuerbar")


# =============================================================================
# COMMAND-DISPATCHING
# =============================================================================

_ACTUATOR_HANDLERS = {
    core_constants.ACTUATOR_HEATER: handle_heater,
    core_constants.ACTUATOR_PUMP:   handle_pump,
    core_constants.ACTUATOR_LED:    handle_led,
}


def on_command_message(topic: str, payload: dict) -> None:
    """MQTT-Callback fuer eingehende Aktor-Befehle.

    Erwartetes Topic-Schema:
        pbr/reactor-01/actuator/<actuator_name>/cmd
    Aktor-Name wird aus dem Topic gelesen, NICHT aus dem Payload-Feld
    (Topic ist authoritativ - das verhindert Spoofing).
    """
    parts = topic.split("/")
    if len(parts) != 5 or parts[2] != "actuator" or parts[4] != "cmd":
        _logger.warning("Topic '%s' entspricht nicht dem Schema - ignoriert.", topic)
        return

    actuator = parts[3]
    handler = _ACTUATOR_HANDLERS.get(actuator)
    if handler is None:
        _logger.warning("Unbekannter Aktor '%s' im Topic - ignoriert.", actuator)
        return

    action_id = payload.get("action_id")
    if not isinstance(action_id, str) or not action_id:
        _logger.warning("Befehl ohne gueltige action_id - ignoriert.")
        return

    # Sofort 'accepted' melden, dann den Handler aufrufen
    publish_status(actuator, action_id, core_constants.ACTUATOR_STATE_ACCEPTED)

    try:
        handler(action_id, payload)
    except Exception as exc:
        _logger.error("Handler-Fehler [%s]: %s", actuator, exc, exc_info=True)
        publish_status(actuator, action_id, core_constants.ACTUATOR_STATE_ERROR,
                       error_details=str(exc),
                       error_code=core_constants.ERROR_CODE_HARDWARE_FAULT)


# =============================================================================
# MAIN
# =============================================================================

def _shutdown() -> None:
    """Alle Pumpen abbrechen, Aktoren auf LOW, GPIO/MQTT/DB schliessen."""
    for event in _active_pump_events.values():
        event.set()
    core_hardware.set_actuator_pin(core_constants.GPIO_PIN_PUMP, False)
    core_hardware.set_actuator_pin(core_constants.GPIO_PIN_HEATER, False)
    core_hardware.set_pwm_duty_cycle(core_constants.GPIO_PIN_LED_PWM, 0)
    core_hardware.cleanup_gpio()
    core_mqtt.mqtt_disconnect()


def main() -> int:
    """Startet GPIO, abonniert das Command-Topic, laeuft bis Signal."""
    if not core_hardware.initialize_gpio():
        _logger.error("GPIO-Initialisierung fehlgeschlagen - Abbruch.")
        return 1

    def _handle_signal(signum, _frame):
        _logger.info("Signal %s empfangen - Skript wird beendet.", signum)
        _shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # Subscription auf alle Aktor-Befehle des Reaktors
    cmd_pattern = core_constants.TOPIC_TEMPLATE_ACTUATOR_CMD.format(
        device_id=core_constants.REACTOR_DEVICE_ID,
        actuator_name="+",
    )
    if not core_mqtt.mqtt_subscribe_topic(cmd_pattern, on_command_message):
        _logger.error("MQTT-Subscribe auf '%s' fehlgeschlagen - Abbruch.",
                      cmd_pattern)
        _shutdown()
        return 1

    _logger.info("Aktor-Steuerung gestartet, lauscht auf %s.", cmd_pattern)
    core_mqtt.mqtt_start_loop(blocking=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
