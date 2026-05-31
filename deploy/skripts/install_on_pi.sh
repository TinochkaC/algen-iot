#!/usr/bin/env bash
# =============================================================================
# Algen-IoT - One-Click-Installation auf Raspberry Pi (Ubuntu/Raspbian)
# =============================================================================
# Voraussetzungen:
#   - Frischer Pi mit Internet
#   - InfluxDB + Mosquitto bereits installiert (siehe deploy/scripts/)
#
# Aufruf:
#   sudo ./deploy/scripts/install_on_pi.sh
# =============================================================================
set -euo pipefail

INSTALL_DIR="/opt/algen-iot"
CONFIG_DIR="/etc/algen_iot"
LOG_DIR="/var/log/algen_iot"
SERVICE_USER="algen"

echo "===> Algen-IoT Installation startet"

# 1) Benutzer anlegen
if ! id "${SERVICE_USER}" &>/dev/null; then
    useradd --system --shell /usr/sbin/nologin --groups gpio,spi,i2c "${SERVICE_USER}"
    echo "  - Benutzer ${SERVICE_USER} angelegt"
fi

# 2) Verzeichnisse
mkdir -p "${INSTALL_DIR}" "${CONFIG_DIR}/config" "${CONFIG_DIR}/certs" "${LOG_DIR}"
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}" "${LOG_DIR}"
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${CONFIG_DIR}"
chmod 750 "${CONFIG_DIR}"

# 3) Python-Venv anlegen
echo "===> Python-venv unter ${INSTALL_DIR}/.venv"
apt-get update -qq
apt-get install -y python3-venv python3-pip git
python3 -m venv "${INSTALL_DIR}/.venv"

# 4) Algen-IoT installieren (vom aktuellen Git-Checkout)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
"${INSTALL_DIR}/.venv/bin/pip" install --upgrade pip
"${INSTALL_DIR}/.venv/bin/pip" install -e "${SCRIPT_DIR}[pi]"

# 5) Beispiel-Konfigs kopieren (falls noch keine vorhanden)
if [ ! -f "${CONFIG_DIR}/config/sensor_ph.json" ]; then
    cp -n "${SCRIPT_DIR}/config.example/"*.json "${CONFIG_DIR}/config/"
    echo "  - Beispiel-Sensor-Konfigs nach ${CONFIG_DIR}/config/ kopiert"
    echo "    !!! Werte mit echten Lab-Kalibrierdaten anpassen !!!"
fi

# 6) Env-Datei vorbereiten
if [ ! -f "${CONFIG_DIR}/algen.env" ]; then
    cp "${SCRIPT_DIR}/.env.example" "${CONFIG_DIR}/algen.env"
    chmod 600 "${CONFIG_DIR}/algen.env"
    chown "${SERVICE_USER}:${SERVICE_USER}" "${CONFIG_DIR}/algen.env"
    echo "  - ${CONFIG_DIR}/algen.env angelegt"
    echo "    !!! INFLUX_TOKEN und MQTT_PASSWORD mit echten Werten fuellen !!!"
fi

# 7) Systemd-Units installieren
cp "${SCRIPT_DIR}/deploy/systemd/"*.service /etc/systemd/system/
systemctl daemon-reload
echo "  - Systemd-Units in /etc/systemd/system/ installiert"

echo ""
echo "===> FERTIG"
echo ""
echo "Naechste Schritte:"
echo "  1) sudo nano ${CONFIG_DIR}/algen.env             # echte Tokens/Passwoerter eintragen"
echo "  2) sudo nano ${CONFIG_DIR}/config/sensor_*.json  # Kalibrierwerte eintragen"
echo "  3) sudo systemctl enable --now algen-capture-reactor"
echo "     sudo systemctl enable --now algen-capture-room"
echo "     sudo systemctl enable --now algen-analyze-algae"
echo "     sudo systemctl enable --now algen-analyze-air"
echo "     sudo systemctl enable --now algen-control-actuators"
echo "     sudo systemctl enable --now algen-bridge-actuator"
echo "  4) sudo journalctl -u algen-capture-reactor -f"
