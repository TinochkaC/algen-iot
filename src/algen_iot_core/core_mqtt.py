"""
core_mqtt.py - Algen-IoT
========================

Zentrale MQTT-Schnittstelle. Stellt sicher, dass alle Skripte:
- DASSELBE Topic-Schema verwenden (pbr/<device_id>/...)
- TLS verwenden (Pflichtenheft 6.3, MoSCoW Must-Have)
- DENSELBEN Mosquitto-Broker mit denselben Credentials nutzen
- KEINE hardcoded Passwoerter im Code haben (Umgebungsvariablen)

Bezieht sich auf:
- Coding Guidelines, Kapitel 3 (core_mqtt.py - erweiterte Liste)
- Datenflussarchitektur und Datenstrukturen, Kapitel 3.4-3.7 (alle Topics)
- Pflichtenheft 4.5.2 + 6.3, Sicherheitskonzept

Autor: Algen-IoT Team
Datum: 2026-05-31
"""

import json
import os
import ssl
import threading
from typing import Callable, Optional

import paho.mqtt.client as mqtt

from algen_iot_core import core_constants
from algen_iot_core import core_logger


_logger = core_logger.get_logger("core_mqtt")


# ============================================================================
# CLIENT-SINGLETON
# ============================================================================

_mqtt_client: Optional[mqtt.Client] = None
_subscriptions: dict[str, Callable] = {}
_client_lock = threading.Lock()


def _build_client() -> mqtt.Client:
    """Erzeugt den Singleton-Client mit korrekter TLS- und Auth-Konfiguration.

    Konfigurationsquellen (in Reihenfolge):
        Env-Var                     | Default
        ----------------------------+--------------------------------------
        MQTT_HOST                   | localhost
        MQTT_PORT                   | 8883 (TLS)
        MQTT_USERNAME               | pi_logic
        MQTT_PASSWORD               | (kein Default - muss gesetzt sein)
        MQTT_TLS_CA                 | /etc/iot/certs/ca.crt
        MQTT_CLIENT_ID              | algen-iot-<rand>

    Returns:
        mqtt.Client: Konfigurierter Client (noch nicht verbunden).

    Raises:
        RuntimeError: Wenn TLS-Zertifikat fehlt oder Passwort leer ist.
    """
    host = os.getenv("MQTT_HOST", core_constants.MQTT_HOST_DEFAULT)
    port = int(os.getenv("MQTT_PORT", str(core_constants.MQTT_PORT_TLS)))
    username = os.getenv("MQTT_USERNAME", core_constants.MQTT_USER_LOGIC)
    password = os.getenv("MQTT_PASSWORD", "")
    ca_path = os.getenv("MQTT_TLS_CA", "/etc/iot/certs/ca.crt")
    client_id = os.getenv("MQTT_CLIENT_ID", "")

    if not password:
        raise RuntimeError(
            "Umgebungsvariable MQTT_PASSWORD ist nicht gesetzt. "
            "Hardcoded Passwoerter sind laut Sicherheitskonzept verboten."
        )

    if port == core_constants.MQTT_PORT_TLS and not os.path.exists(ca_path):
        raise RuntimeError(
            f"TLS aktiv (Port {port}), aber CA-Zertifikat fehlt: {ca_path}"
        )

    client = mqtt.Client(
        client_id=client_id or None,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        protocol=mqtt.MQTTv5,
    )
    client.username_pw_set(username, password)
    client.reconnect_delay_set(min_delay=1, max_delay=30)

    if port == core_constants.MQTT_PORT_TLS:
        tls_ctx = ssl.create_default_context(cafile=ca_path)
        client.tls_set_context(tls_ctx)
    else:
        _logger.warning(
            "MQTT verbindet auf Port %d ohne TLS. Nur fuer lokale Tests zulaessig.",
            port,
        )

    client.on_connect = _on_connect_default
    client.on_message = _on_message_dispatcher

    try:
        client.connect(host, port, keepalive=core_constants.MQTT_KEEPALIVE_S)
        _logger.info("MQTT verbunden (host=%s, port=%d, user=%s, tls=%s).",
                      host, port, username, port == core_constants.MQTT_PORT_TLS)
    except Exception as exc:
        _logger.error("MQTT-Verbindung fehlgeschlagen: %s", exc)
        raise

    return client


def _get_client() -> mqtt.Client:
    """Lazy-Singleton: Verbindung wird beim ersten Aufruf aufgebaut."""
    global _mqtt_client
    with _client_lock:
        if _mqtt_client is None:
            _mqtt_client = _build_client()
        return _mqtt_client


def _on_connect_default(client, userdata, flags, reason_code, properties=None):
    """Default-Callback: Re-Subscription nach Reconnect.

    paho-mqtt resubscribiert bei reconnect_delay_set automatisch nicht --
    wir muessen das selbst tun.
    """
    if int(reason_code) == 0:
        for topic in list(_subscriptions.keys()):
            client.subscribe(topic, qos=core_constants.MQTT_QOS_AT_LEAST_ONCE)
            _logger.info("Re-Subscribe: %s", topic)
    else:
        _logger.error("MQTT-Connect-Fehler (reason_code=%s).", reason_code)


def _on_message_dispatcher(client, userdata, msg):
    """Dispatch eingehender Nachrichten an die registrierten Callbacks.

    Sucht die passendste Subscription (exakte Treffer vor Wildcards) und
    ruft deren Callback mit (topic, payload_dict) auf.
    """
    handler = None

    # 1) Exakter Treffer
    if msg.topic in _subscriptions:
        handler = _subscriptions[msg.topic]
    else:
        # 2) Wildcard-Match (+ und #)
        for pattern, cb in _subscriptions.items():
            if mqtt.topic_matches_sub(pattern, msg.topic):
                handler = cb
                break

    if handler is None:
        return

    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _logger.error("Ungueltiges JSON auf %s: %s", msg.topic, exc)
        return

    try:
        handler(msg.topic, payload)
    except Exception as exc:
        # Coding Guidelines Kapitel 5: Callbacks duerfen das Skript nie
        # crashen lassen.
        _logger.error("Callback-Fehler [%s]: %s", msg.topic, exc)


# ============================================================================
# 1. PUBLISH-FUNKTIONEN (Coding Guidelines core_mqtt.py)
# ============================================================================

def mqtt_publish_command(actuator_name: str, json_payload: dict) -> bool:
    """Publiziert einen Aktor-Stellbefehl.

    Konstruiert das Topic:
        pbr/reactor-01/actuator/<actuator_name>/cmd

    Args:
        actuator_name: "heater", "pump" oder "led".
        json_payload: Standardisiertes JSON aus build_standard_json
            (action_id, actuator, is_enabled, ...).

    Returns:
        bool: True, wenn der Publish-Aufruf rc == 0 liefert.
    """
    if actuator_name not in core_constants.ACTUATORS:
        _logger.error("Unbekannter Aktor: %s", actuator_name)
        return False

    topic = core_constants.TOPIC_TEMPLATE_ACTUATOR_CMD.format(
        device_id=core_constants.REACTOR_DEVICE_ID,
        actuator_name=actuator_name,
    )
    # mqtt_topic_used ins Payload schreiben, damit es im DB-Log
    # nachvollziehbar ist (Datenflussarch. 4.3).
    json_payload.setdefault("mqtt_topic_used", topic)
    json_payload.setdefault("actuator", actuator_name)
    return _publish(topic, json_payload, retain=False)


def mqtt_publish_status(actuator_name: str, json_payload: dict) -> bool:
    """Publiziert eine Aktor-Rueckmeldung (accepted/running/completed/...).

    Topic:
        pbr/reactor-01/actuator/<actuator_name>/status

    Args:
        actuator_name: "heater", "pump" oder "led".
        json_payload: action_id, actuator, state, timestamp, error_details.

    Returns:
        bool: True bei Erfolg.
    """
    if actuator_name not in core_constants.ACTUATORS:
        _logger.error("Unbekannter Aktor: %s", actuator_name)
        return False

    topic = core_constants.TOPIC_TEMPLATE_ACTUATOR_STATUS.format(
        device_id=core_constants.REACTOR_DEVICE_ID,
        actuator_name=actuator_name,
    )
    json_payload.setdefault("actuator", actuator_name)
    return _publish(topic, json_payload, retain=False)


def mqtt_publish_alarm(device_name: str,
                       component_type: str,
                       component_name: str,
                       json_payload: dict) -> bool:
    """Publiziert einen Alarm (Sensor oder Aktor).

    Universeller Publisher fuer beide Alarm-Typen:
        - Sensor : pbr/<device_name>/alarm/sensor/<component_name>
        - Aktor  : pbr/<device_name>/alarm/actuator/<component_name>

    Args:
        device_name: "reactor-01" oder "roomnode-01".
        component_type: "sensor" oder "actuator".
        component_name: z. B. "ph", "co2", "pump".
        json_payload: Alarm-JSON (siehe Datenflussarch. 4.9/4.10).

    Returns:
        bool: True bei Erfolg.
    """
    if component_type not in ("sensor", "actuator"):
        _logger.error("Ungueltiger component_type: %s", component_type)
        return False

    template = (core_constants.TOPIC_TEMPLATE_ALARM_SENSOR
                if component_type == "sensor"
                else core_constants.TOPIC_TEMPLATE_ALARM_ACTUATOR)
    topic = template.format(device_id=device_name,
                             sensor_name=component_name,
                             actuator_name=component_name)
    json_payload.setdefault("device_id", device_name)
    json_payload.setdefault("mqtt_topic_used", topic)
    # Alarme retained, damit das Dashboard nach Reconnect den letzten
    # Alarm-Zustand sieht (Datenflussarch. 3.7).
    return _publish(topic, json_payload, retain=True)


def _publish(topic: str, payload: dict, retain: bool) -> bool:
    """Interne Publish-Funktion mit Fehlerbehandlung."""
    try:
        client = _get_client()
    except RuntimeError as exc:
        _logger.error("Publish: %s", exc)
        return False

    try:
        info = client.publish(
            topic=topic,
            payload=json.dumps(payload, ensure_ascii=False),
            qos=core_constants.MQTT_QOS_AT_LEAST_ONCE,
            retain=retain,
        )
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            _logger.error("Publish-Fehler [%s] rc=%s", topic, info.rc)
            return False
        _logger.info("Publish ok [%s].", topic)
        return True
    except Exception as exc:
        _logger.error("Publish-Exception [%s]: %s", topic, exc)
        return False


# ============================================================================
# 2. SUBSCRIBE-FUNKTIONEN (Coding Guidelines erweiterte Liste)
# ============================================================================

def mqtt_subscribe_topic(topic_string: str,
                          callback_function: Callable[[str, dict], None]
                          ) -> bool:
    """Abonniert ein Topic (oder Wildcard) und bindet einen Callback.

    Der Callback wird mit (topic, payload_dict) aufgerufen. Wildcards
    `+` (genau ein Segment) und `#` (alle restlichen) werden unterstuetzt.

    Beispiel:
        def on_alarm(topic, payload):
            ...
        mqtt_subscribe_topic("pbr/+/alarm/#", on_alarm)

    Args:
        topic_string: Konkretes Topic oder Wildcard.
        callback_function: Callable(topic: str, payload: dict) -> None.

    Returns:
        bool: True, wenn die Subscription erfolgreich war.
    """
    try:
        client = _get_client()
    except RuntimeError as exc:
        _logger.error("Subscribe: %s", exc)
        return False

    try:
        result, _ = client.subscribe(
            topic_string,
            qos=core_constants.MQTT_QOS_AT_LEAST_ONCE,
        )
        if result != mqtt.MQTT_ERR_SUCCESS:
            _logger.error("Subscribe-Fehler [%s] rc=%s", topic_string, result)
            return False
        _subscriptions[topic_string] = callback_function
        _logger.info("Subscribe ok [%s].", topic_string)
        return True
    except Exception as exc:
        _logger.error("Subscribe-Exception [%s]: %s", topic_string, exc)
        return False


def mqtt_start_loop(blocking: bool = True) -> None:
    """Startet die MQTT-Netzwerkschleife.

    Args:
        blocking: True (Default) ruft loop_forever() auf und blockiert
            das aktuelle Thread bis KeyboardInterrupt.
            False ruft loop_start() auf (Hintergrundthread) - das Skript
            muss dann selbst eine Hauptschleife haben.

    Returns:
        None.
    """
    try:
        client = _get_client()
    except RuntimeError as exc:
        _logger.error("mqtt_start_loop: %s", exc)
        return

    try:
        if blocking:
            client.loop_forever()
        else:
            client.loop_start()
    except KeyboardInterrupt:
        _logger.info("MQTT-Loop durch KeyboardInterrupt beendet.")
    except Exception as exc:
        _logger.error("MQTT-Loop-Fehler: %s", exc)


def mqtt_disconnect() -> None:
    """Trennt die MQTT-Verbindung sauber (am Skriptende aufrufen)."""
    global _mqtt_client
    if _mqtt_client is None:
        return
    try:
        _mqtt_client.loop_stop()
        _mqtt_client.disconnect()
        _logger.info("MQTT-Verbindung getrennt.")
    except Exception as exc:
        _logger.warning("MQTT-Disconnect-Fehler: %s", exc)
    finally:
        _mqtt_client = None
        _subscriptions.clear()
