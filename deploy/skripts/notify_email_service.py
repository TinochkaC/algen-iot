"""
notify_email_service.py - Algen-IoT
===================================

E-Mail-Benachrichtigungsdienst: hoert auf alle kritischen Alarme via MQTT
und versendet bei is_critical=true bzw. alert_level="critical" eine E-Mail
an die in Umgebungsvariablen hinterlegten Empfaenger.

Vorgehen (Datenflussarchitektur Kapitel 3.6):
  1. Subscription auf pbr/+/alarm/sensor/+ und pbr/+/alarm/actuator/+.
  2. Wenn is_critical=true (oder alert_level=critical): E-Mail vorbereiten.
  3. Anti-Spam-Cooldown: pro (device, component, error_code/sensor_name)
     wird nur alle ALARM_COOLDOWN_S Sekunden EINE Mail gesendet.
  4. Versand via SMTP (Zugangsdaten ausschliesslich aus Env-Variablen).
  5. Erfolgreichen oder fehlgeschlagenen Versand in MEASUREMENT_NOTIFICATIONS
     protokollieren.

Sicherheits-Hinweis: SMTP_PASSWORD steht NIE im Code, ausschliesslich in
der Umgebungsvariable.

Autor: Algen-IoT Team
Datum: 2026-05-31
"""

import os
import signal
import smtplib
import sys
import threading
from email.message import EmailMessage

from algen_iot_core import (
    core_constants,
    core_database,
    core_logger,
    core_mqtt,
    core_utils,
)


_logger = core_logger.get_logger(
    "notify_email_service",
    log_file_path=f"{core_constants.LOG_DIRECTORY_DEFAULT}/notify_email_service.log",
)


# =============================================================================
# KONFIGURATION (aus Umgebungsvariablen, KEINE Defaults fuer Secrets!)
# =============================================================================

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "alerts@pbr-project.local")
SMTP_TO_ADMIN = os.getenv("SMTP_TO_ADMIN", "")
SMTP_TO_OPERATOR = os.getenv("SMTP_TO_OPERATOR", "")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() == "true"


def _validate_smtp_config() -> bool:
    """Prueft beim Start, ob alle SMTP-Variablen vorhanden sind."""
    missing = [name for name, value in {
        "SMTP_HOST":     SMTP_HOST,
        "SMTP_USERNAME": SMTP_USERNAME,
        "SMTP_PASSWORD": SMTP_PASSWORD,
        "SMTP_TO_ADMIN": SMTP_TO_ADMIN,
    }.items() if not value]
    if missing:
        _logger.error("Fehlende SMTP-Umgebungsvariablen: %s", ", ".join(missing))
        return False
    return True


# =============================================================================
# ANTI-SPAM-COOLDOWN
# =============================================================================
# Mapping (device_id, component, key) -> letzter timestamp in UNIX-Sekunden
_last_sent_per_key: dict[tuple[str, str, str], int] = {}
_cooldown_lock = threading.Lock()


def _is_in_cooldown(device_id: str, component: str, key: str) -> bool:
    """Prueft, ob fuer diesen Alarm-Typ noch ein Cooldown aktiv ist."""
    with _cooldown_lock:
        last = _last_sent_per_key.get((device_id, component, key))
    if last is None:
        return False
    age_s = core_utils.get_current_timestamp() - last
    return age_s < core_constants.ALARM_COOLDOWN_CRITICAL_S


def _remember_sent(device_id: str, component: str, key: str) -> None:
    """Merkt sich den Zeitpunkt eines erfolgreich gesendeten Alarms."""
    with _cooldown_lock:
        _last_sent_per_key[(device_id, component, key)] = (
            core_utils.get_current_timestamp()
        )


# =============================================================================
# MAIL-VERSAND
# =============================================================================

def _build_subject(device_id: str,
                    component_type: str,
                    component_name: str,
                    payload: dict) -> str:
    """Baut den E-Mail-Betreff."""
    level = payload.get("alert_level", "critical").upper()
    return (f"[Algen-IoT][{level}] {device_id} / "
            f"{component_type}/{component_name}")


def _build_body(device_id: str,
                 component_type: str,
                 component_name: str,
                 payload: dict) -> str:
    """Baut den E-Mail-Body als Klartext."""
    lines = [
        "Ein kritischer Alarm wurde im Algen-IoT-System ausgeloest.",
        "",
        f"  Geraet:           {device_id}",
        f"  Komponente:       {component_type}/{component_name}",
        f"  Zeitpunkt (UNIX): {payload.get('timestamp', 'unbekannt')}",
        f"  alarm_id:         {payload.get('alarm_id', '?')}",
        "",
        "Details:",
    ]
    for key in ("current_value", "unit", "status", "error_code",
                "error_details", "alert_level"):
        if key in payload and payload[key] not in (None, ""):
            lines.append(f"  - {key}: {payload[key]}")
    lines.extend([
        "",
        "Bitte pruefen Sie das Dashboard und ergreifen Sie ggf. Massnahmen.",
        "",
        "Diese E-Mail wurde automatisch vom Photobioreaktor-System gesendet.",
    ])
    return "\n".join(lines)


def send_email(subject: str, body: str, recipients: list[str]) -> bool:
    """Versendet eine E-Mail via SMTP.

    Returns:
        bool: True bei Erfolg.
    """
    if not recipients:
        return False
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = SMTP_FROM
    message["To"] = ", ".join(recipients)
    message.set_content(body)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as smtp:
            smtp.ehlo()
            if SMTP_USE_TLS:
                smtp.starttls()
                smtp.ehlo()
            smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
            smtp.send_message(message)
        return True
    except (smtplib.SMTPException, OSError) as exc:
        _logger.error("SMTP-Versand fehlgeschlagen: %s", exc)
        return False


# =============================================================================
# CALLBACK: ALARM EMPFANGEN
# =============================================================================

def on_alarm(topic: str, payload: dict) -> None:
    """Wird bei jedem MQTT-Alarm aufgerufen.

    Filtert nicht-kritische Alarme heraus, prueft Cooldown und versendet
    die Mail. Protokolliert das Ergebnis in MEASUREMENT_NOTIFICATIONS.
    """
    parts = topic.split("/")
    if len(parts) != 5 or parts[2] != "alarm":
        return

    device_id = parts[1]
    component_type = parts[3]
    component_name = parts[4]

    is_critical = (
        bool(payload.get("is_critical", False))
        or payload.get("alert_level") == core_constants.ALERT_LEVEL_CRITICAL
    )
    if not is_critical:
        return

    # Cooldown-Schluessel: error_code (bei Aktoren) oder sensor-Status
    cooldown_key = (payload.get("error_code")
                    or payload.get("status")
                    or "general")

    if _is_in_cooldown(device_id, component_name, cooldown_key):
        _logger.info("Alarm [%s/%s] im Cooldown - keine Mail.",
                     device_id, component_name)
        return

    subject = _build_subject(device_id, component_type, component_name, payload)
    body = _build_body(device_id, component_type, component_name, payload)
    recipients = [r for r in (SMTP_TO_ADMIN, SMTP_TO_OPERATOR) if r]

    success = send_email(subject, body, recipients)

    if success:
        _remember_sent(device_id, component_name, cooldown_key)
        _logger.info("Alarm-Mail [%s/%s] an %d Empfaenger gesendet.",
                     device_id, component_name, len(recipients))

    # Protokoll-Eintrag in DB
    log_payload = core_utils.build_standard_json(
        id_prefix=core_constants.UUID_PREFIX_NOTIFICATION,
        parameters_dict={
            "device_id":      device_id,
            "component_type": component_type,
            "component_name": component_name,
            "alarm_id":       payload.get("alarm_id"),
            "recipients":     ", ".join(recipients),
            "subject":        subject,
            "is_sent":        success,
            "channel":        "email",
        },
        id_field_name="notification_id",
    )
    core_database.db_insert_record(
        table_name=core_constants.MEASUREMENT_NOTIFICATIONS,
        json_payload=log_payload,
    )


# =============================================================================
# MAIN
# =============================================================================

def main() -> int:
    if not _validate_smtp_config():
        return 1

    if not core_mqtt.mqtt_subscribe_topic("pbr/+/alarm/sensor/+", on_alarm):
        _logger.error("MQTT-Subscribe (alarm/sensor) fehlgeschlagen.")
        return 1
    if not core_mqtt.mqtt_subscribe_topic("pbr/+/alarm/actuator/+", on_alarm):
        _logger.error("MQTT-Subscribe (alarm/actuator) fehlgeschlagen.")
        return 1

    def _handle_signal(signum, _frame):
        _logger.info("Signal %s empfangen - Skript wird beendet.", signum)
        core_mqtt.mqtt_disconnect()
        core_database.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    _logger.info("E-Mail-Benachrichtigung gestartet "
                 "(SMTP %s:%d, Cooldown %ds).",
                 SMTP_HOST, SMTP_PORT, core_constants.ALARM_COOLDOWN_CRITICAL_S)

    core_mqtt.mqtt_start_loop(blocking=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
