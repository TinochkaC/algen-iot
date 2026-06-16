"""
bridge_dashboard_alerts.py - Algen-IoT
======================================

Echtzeit-Alarmweiterleitung an das Dashboard-Frontend.

Vorgehen (Datenflussarchitektur Kapitel 3.7):
  1. Subscription auf alle Alarm-Topics (pbr/+/alarm/#).
  2. Pro eingehendem Alarm wird ein kompaktes Dashboard-Payload gebaut:
     - alert_level (info/warning/critical) -> display_type (toast/modal/inline)
     - Farbe gemaess Spec (Datenflussarch. 4.7)
  3. Das Dashboard-Payload wird auf das MQTT-Topic
     "dashboard/alerts" publiziert (retain=true, damit das Frontend
     den letzten Alarm nach Reconnect sofort sieht).
  4. Parallel wird der Alert in MEASUREMENT_ALARMS persistiert (falls noch
     nicht durch die Status-Bridge geschehen) und mit ui_status="unresolved"
     versehen.

Hinweis: Diese Bruecke ist die FRONTEND-Variante. Die DB-Persistierung der
Alarme passiert primaer in bridge_andanalyse_mqtt_actuator_status.py - das
hier dient nur dazu, ein Real-Time-Frontend zu bedienen, das eventuell
keinen direkten DB-Zugriff hat.

Autor: Algen-IoT Team
Datum: 2026-05-31
"""

import signal
import sys

from algen_iot_core import (
    core_constants,
    core_logger,
    core_mqtt,
    core_utils,
)


_logger = core_logger.get_logger(
    "bridge_dashboard_alerts",
    log_file_path=f"{core_constants.LOG_DIRECTORY_DEFAULT}/bridge_dashboard_alerts.log",
)


# Topic, auf das das Dashboard-Frontend hoert
DASHBOARD_ALERT_TOPIC = "dashboard/alerts"


# =============================================================================
# MAPPING: alert_level -> Anzeige-Eigenschaften
# =============================================================================
# Quelle: Datenflussarch. 4.6 + 4.7
_LEVEL_DISPLAY_MAP = {
    core_constants.ALERT_LEVEL_CRITICAL: {
        "display_type": core_constants.DISPLAY_TYPE_MODAL,
        "toast_color":  core_constants.TOAST_COLOR_ERROR,
    },
    core_constants.ALERT_LEVEL_WARNING: {
        "display_type": core_constants.DISPLAY_TYPE_TOAST,
        "toast_color":  core_constants.TOAST_COLOR_WARNING,
    },
    core_constants.ALERT_LEVEL_INFO: {
        "display_type": core_constants.DISPLAY_TYPE_INLINE,
        "toast_color":  core_constants.TOAST_COLOR_INFO,
    },
}


# =============================================================================
# CALLBACK: ALARM EMPFANGEN
# =============================================================================

def on_alarm(topic: str, payload: dict) -> None:
    """Subscription-Callback fuer alle Alarm-Topics."""
    parts = topic.split("/")
    if len(parts) < 4 or parts[2] != "alarm":
        return

    device_id = parts[1]
    component_type = parts[3] if len(parts) >= 5 else "unknown"
    component_name = parts[4] if len(parts) >= 5 else "unknown"

    alert_level = (
        payload.get("alert_level")
        or core_constants.ALERT_LEVEL_INFO
    )
    display_props = _LEVEL_DISPLAY_MAP.get(
        alert_level,
        _LEVEL_DISPLAY_MAP[core_constants.ALERT_LEVEL_INFO],
    )

    dashboard_payload = core_utils.build_standard_json(
        id_prefix=core_constants.UUID_PREFIX_DASHBOARD,
        parameters_dict={
            "alarm_id":       payload.get("alarm_id"),
            "device_id":      device_id,
            "component_type": component_type,
            "component_name": component_name,
            "alert_level":    alert_level,
            "display_type":   display_props["display_type"],
            "toast_color":    display_props["toast_color"],
            "ui_status":      core_constants.UI_STATUS_UNRESOLVED,
            "title":          _build_title(device_id, component_type,
                                            component_name, alert_level),
            "message":        _build_message(payload),
            "source_topic":   topic,
        },
        id_field_name="event_id",
    )

    # Direkt an das Frontend publishen
    if _publish_to_dashboard(dashboard_payload):
        _logger.info("Dashboard-Alert ausgeliefert [%s/%s/%s] level=%s.",
                     device_id, component_type, component_name, alert_level)
    else:
        _logger.error("Dashboard-Alert konnte NICHT publiziert werden.")


def _build_title(device_id: str,
                  component_type: str,
                  component_name: str,
                  alert_level: str) -> str:
    """Baut die kurze Anzeige-Ueberschrift fuer das Dashboard."""
    return f"[{alert_level.upper()}] {device_id} - {component_type}/{component_name}"


def _build_message(payload: dict) -> str:
    """Baut die ausfuehrliche Anzeige-Nachricht aus dem Alarm-Payload."""
    parts = []
    if "error_code" in payload:
        parts.append(f"Code: {payload['error_code']}")
    if "error_details" in payload:
        parts.append(payload["error_details"])
    if "current_value" in payload and "unit" in payload:
        parts.append(f"Wert: {payload['current_value']} {payload['unit']}")
    if "status" in payload:
        parts.append(f"Status: {payload['status']}")
    return " | ".join(parts) if parts else "Alarm ausgeloest"


def _publish_to_dashboard(payload: dict) -> bool:
    """Publiziert das Dashboard-Payload auf das spezielle Frontend-Topic.

    retain=True sorgt dafuer, dass ein neu verbundenes Dashboard sofort
    den letzten Alarm-Zustand sieht. Wenn der Alarm quittiert ist, sollte
    das Dashboard selbst eine leere retained-Message schicken, um das
    Topic zu loeschen.
    """
    # Wir nutzen den internen Publish-Mechanismus von core_mqtt, fuer ein
    # nicht-template-Topic ist das ueber den Singleton-Client direkt
    # erreichbar.
    import json
    import paho.mqtt.client as mqtt

    client = core_mqtt._get_client()  # interner Singleton
    info = client.publish(
        topic=DASHBOARD_ALERT_TOPIC,
        payload=json.dumps(payload, ensure_ascii=False),
        qos=core_constants.MQTT_QOS_AT_LEAST_ONCE,
        retain=True,
    )
    return info.rc == mqtt.MQTT_ERR_SUCCESS


# =============================================================================
# MAIN
# =============================================================================

def main() -> int:
    # Wildcard-Subscription auf alle Alarme
    if not core_mqtt.mqtt_subscribe_topic(
            core_constants.TOPIC_WILDCARD_ALL_ALARMS, on_alarm):
        _logger.error("MQTT-Subscribe fehlgeschlagen - Abbruch.")
        return 1

    def _handle_signal(signum, _frame):
        _logger.info("Signal %s empfangen - Skript wird beendet.", signum)
        core_mqtt.mqtt_disconnect()
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    _logger.info("Dashboard-Alert-Bruecke gestartet (Topic: %s).",
                 DASHBOARD_ALERT_TOPIC)

    core_mqtt.mqtt_start_loop(blocking=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
