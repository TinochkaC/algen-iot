"""
bridge_andanalyse_mqtt_actuator_status.py - Algen-IoT
=====================================================

Konsolidiertes Bruecken-Skript fuer Aktor-Status und Alarme.
Ersetzt die drei Vorgaengerskripte (aktor_status_bridge.py,
capture_actor_status.py, control_actor_status_bridge.py).

Aufgaben (Datenflussarchitektur Kapitel 3.5):

  1. Abonniert pbr/+/actuator/+/status -> persistiert jeden Statuspunkt
     in MEASUREMENT_ACTUATOR_STATUS (Bucket algen_system, 30d).

  2. Abonniert pbr/+/alarm/actuator/+ und pbr/+/alarm/sensor/+ ->
     persistiert in MEASUREMENT_ALARMS mit ui_status="unresolved".

  3. *WATCHDOG* check_active_timeouts(): laeuft alle 2 Sekunden und
     prueft, ob ein Aktor laenger als ACTUATOR_TIMEOUT_MS (= 5000ms) im
     state="running" haengt. Falls ja:
       a) DB-Status auf "timeout" aktualisieren
       b) Alarm auf pbr/<device>/alarm/actuator/<actuator> publishen
       c) Alarm-Datensatz mit ui_status="unresolved" in DB schreiben

Autor: Algen-IoT Team
Datum: 2026-05-31
"""

import signal
import sys
import threading
import time

from algen_iot_core import (
    core_constants,
    core_database,
    core_logger,
    core_mqtt,
    core_utils,
)


_logger = core_logger.get_logger(
    "bridge_andanalyse_mqtt_actuator_status",
    log_file_path=f"{core_constants.LOG_DIRECTORY_DEFAULT}/bridge_actuator_status.log",
)


# =============================================================================
# STATE: aktive running-Aktionen (fuer Watchdog)
# =============================================================================
# Mapping action_id -> {"state": str, "started_ms": int, "actuator": str,
#                       "device_id": str}
_active_actions: dict[str, dict] = {}
_active_actions_lock = threading.Lock()
_shutdown_event = threading.Event()


# =============================================================================
# CALLBACK: AKTOR-STATUS
# =============================================================================

def on_actuator_status(topic: str, payload: dict) -> None:
    """Subscription-Callback fuer pbr/+/actuator/+/status.

    Erwartetes Payload (Datenflussarch. 4.4):
      action_id, actuator, state, timestamp, error_details? (nur bei error)
    """
    parts = topic.split("/")
    if len(parts) != 5 or parts[2] != "actuator" or parts[4] != "status":
        _logger.warning("Unerwartetes Status-Topic '%s' - ignoriert.", topic)
        return

    device_id = parts[1]
    actuator = parts[3]

    state = payload.get("state")
    if state not in core_constants.ACTUATOR_STATE_VALID_VALUES:
        _logger.warning("Ungueltiger state '%s' auf %s - ignoriert.", state, topic)
        return

    action_id = payload.get("action_id")
    if not isinstance(action_id, str) or not action_id:
        _logger.warning("Status-Nachricht ohne action_id - ignoriert.")
        return

    # 1) In DB persistieren
    full_payload = {
        **payload,
        "device_id":  device_id,
        "actuator":   actuator,
        "topic_used": topic,
    }
    core_database.db_insert_record(
        table_name=core_constants.MEASUREMENT_ACTUATOR_STATUS,
        json_payload=full_payload,
    )

    # 2) In-Memory-State fuer Watchdog aktualisieren
    with _active_actions_lock:
        if state == core_constants.ACTUATOR_STATE_RUNNING:
            _active_actions[action_id] = {
                "state":      state,
                "started_ms": int(time.time() * 1000),
                "actuator":   actuator,
                "device_id":  device_id,
            }
        elif state in core_constants.ACTUATOR_STATE_TERMINAL:
            _active_actions.pop(action_id, None)

    _logger.info("Status %s [%s/%s] action_id=%s gespeichert.",
                 state, device_id, actuator, action_id)


# =============================================================================
# CALLBACK: ALARME
# =============================================================================

def on_alarm(topic: str, payload: dict) -> None:
    """Subscription-Callback fuer pbr/+/alarm/sensor/+ und pbr/+/alarm/actuator/+."""
    parts = topic.split("/")
    if len(parts) != 5 or parts[2] != "alarm":
        _logger.warning("Unerwartetes Alarm-Topic '%s' - ignoriert.", topic)
        return

    device_id = parts[1]
    component_type = parts[3]  # "sensor" oder "actuator"
    component_name = parts[4]

    if component_type not in ("sensor", "actuator"):
        return

    # Alarm-Datensatz mit ui_status="unresolved" (Datenflussarch. 3.8)
    full_payload = {
        **payload,
        "device_id":      device_id,
        "component_type": component_type,
        "component_name": component_name,
        "ui_status":      core_constants.UI_STATUS_UNRESOLVED,
        "topic_used":     topic,
    }
    core_database.db_insert_record(
        table_name=core_constants.MEASUREMENT_ALARMS,
        json_payload=full_payload,
    )
    _logger.warning("Alarm [%s/%s/%s] persistiert (alarm_id=%s).",
                    device_id, component_type, component_name,
                    payload.get("alarm_id"))


# =============================================================================
# WATCHDOG (check_active_timeouts)
# =============================================================================

def check_active_timeouts() -> None:
    """Watchdog-Schleife: alle 2s alle running-Aktionen pruefen."""
    while not _shutdown_event.is_set():
        try:
            _check_timeouts_once()
        except Exception as exc:
            _logger.error("Watchdog-Fehler: %s", exc, exc_info=True)

        # Warten mit Cancel-Moeglichkeit
        _shutdown_event.wait(timeout=2.0)


def _check_timeouts_once() -> None:
    """Eine Runde Timeout-Pruefung."""
    now_ms = int(time.time() * 1000)
    expired: list[tuple[str, dict]] = []

    with _active_actions_lock:
        for action_id, info in list(_active_actions.items()):
            if info["state"] != core_constants.ACTUATOR_STATE_RUNNING:
                continue
            age_ms = now_ms - info["started_ms"]
            if age_ms > core_constants.ACTUATOR_TIMEOUT_MS:
                expired.append((action_id, info))
                # Aus dem aktiven Set entfernen, damit wir nicht doppelt
                # alarmieren.
                del _active_actions[action_id]

    for action_id, info in expired:
        _handle_timeout(action_id, info)


def _handle_timeout(action_id: str, info: dict) -> None:
    """Behandlung einer einzelnen abgelaufenen Aktion."""
    actuator = info["actuator"]
    device_id = info["device_id"]

    _logger.error("WATCHDOG: action_id=%s (%s/%s) > %dms - timeout!",
                  action_id, device_id, actuator,
                  core_constants.ACTUATOR_TIMEOUT_MS)

    # 1) DB-State auf "timeout" aktualisieren
    core_database.db_update_record(
        table_name=core_constants.MEASUREMENT_ACTUATOR_STATUS,
        record_id=action_id,
        update_data={
            "actuator":      actuator,
            "device_id":     device_id,
            "state":         core_constants.ACTUATOR_STATE_TIMEOUT,
            "error_code":    core_constants.ERROR_CODE_TIMEOUT_EXCEEDED,
            "error_details": f"Aktor antwortete nicht innerhalb "
                             f"{core_constants.ACTUATOR_TIMEOUT_MS}ms.",
        },
    )

    # 2) Alarm-Topic publishen
    alarm_payload = core_utils.build_standard_json(
        id_prefix=core_constants.UUID_PREFIX_ALARM,
        parameters_dict={
            "actuator":      actuator,
            "action_id":     action_id,
            "error_code":    core_constants.ERROR_CODE_TIMEOUT_EXCEEDED,
            "error_details": "Watchdog-Timeout (5000ms ueberschritten).",
            "alert_level":   core_constants.ALERT_LEVEL_CRITICAL,
            "is_critical":   True,
        },
        id_field_name="alarm_id",
    )
    core_mqtt.mqtt_publish_alarm(
        device_name=device_id,
        component_type="actuator",
        component_name=actuator,
        json_payload=alarm_payload,
    )

    # 3) Alarm mit ui_status=unresolved in DB
    alarm_payload["ui_status"] = core_constants.UI_STATUS_UNRESOLVED
    alarm_payload["component_type"] = "actuator"
    alarm_payload["component_name"] = actuator
    alarm_payload["device_id"] = device_id
    core_database.db_insert_record(
        table_name=core_constants.MEASUREMENT_ALARMS,
        json_payload=alarm_payload,
    )


# =============================================================================
# MAIN
# =============================================================================

def _shutdown() -> None:
    _shutdown_event.set()
    core_mqtt.mqtt_disconnect()
    core_database.close()


def main() -> int:
    # Subscriptions
    if not core_mqtt.mqtt_subscribe_topic(
            core_constants.TOPIC_WILDCARD_ALL_STATUS, on_actuator_status):
        _logger.error("MQTT-Subscribe (status) fehlgeschlagen - Abbruch.")
        return 1
    if not core_mqtt.mqtt_subscribe_topic("pbr/+/alarm/sensor/+", on_alarm):
        _logger.error("MQTT-Subscribe (alarm/sensor) fehlgeschlagen - Abbruch.")
        return 1
    if not core_mqtt.mqtt_subscribe_topic("pbr/+/alarm/actuator/+", on_alarm):
        _logger.error("MQTT-Subscribe (alarm/actuator) fehlgeschlagen - Abbruch.")
        return 1

    core_mqtt.mqtt_start_loop(blocking=False)

    # Watchdog im eigenen Thread
    watchdog = threading.Thread(target=check_active_timeouts, daemon=True)
    watchdog.start()

    def _handle_signal(signum, _frame):
        _logger.info("Signal %s empfangen.", signum)
        _shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    _logger.info("Bruecken-Skript laeuft (Status + Alarm + Watchdog %dms).",
                 core_constants.ACTUATOR_TIMEOUT_MS)

    # Hauptthread im Sleep-Loop - Arbeit laeuft in Callbacks und Watchdog
    while not _shutdown_event.is_set():
        _shutdown_event.wait(timeout=60.0)

    return 0


if __name__ == "__main__":
    sys.exit(main())
