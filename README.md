# Algen-IoT

> **Photobioreaktor-Steuerung für Chlorella vulgaris** auf Raspberry Pi.
> Sensorerfassung, MQTT-gestützte Aktorik, biologische Analyse, Grafana-Dashboard.

[![Tests](https://github.com/IHR-USER/algen-iot/actions/workflows/tests.yml/badge.svg)](https://github.com/IHR-USER/algen-iot/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Schnellstart

### Entwicklung (lokal)

```bash
git clone https://github.com/IHR-USER/algen-iot.git
cd algen-iot

python3 -m venv .venv
source .venv/bin/activate

pip install -e ".[dev]"

cp .env.example .env
nano .env  # echte Tokens/Passwörter eintragen

pytest tests/ -v
```

### Deployment (Raspberry Pi)

```bash
# Auf dem Pi:
git clone https://github.com/IHR-USER/algen-iot.git /tmp/algen-iot
cd /tmp/algen-iot
sudo ./deploy/scripts/install_on_pi.sh

# Konfiguration:
sudo nano /etc/algen_iot/algen.env             # Tokens
sudo nano /etc/algen_iot/config/sensor_*.json  # Kalibrierwerte

# Services aktivieren:
sudo systemctl enable --now algen-capture-reactor
sudo systemctl enable --now algen-capture-room
# ... (siehe deploy/systemd/)
```

---

## Architektur (Kurzfassung)

```
┌───────────────┐  MQTT (TLS, 8883)   ┌──────────────────┐
│   Sensoren    │ ──── pbr/.../...... │  Mosquitto       │
│ (I2C/SPI/...) │                     │  Broker          │
└───────────────┘                     └────────┬─────────┘
        │                                      │
        ▼                                      ▼
┌─────────────────────┐               ┌──────────────────┐
│ capture_*-Skripte   │               │ control_/notify_-│
│ (Datenerfassung)    │               │ Skripte          │
└─────────┬───────────┘               └─────────┬────────┘
          │                                     │
          │       ┌─────────────────────┐       │
          └─────► │  InfluxDB v2        │ ◄─────┘
                  │  (Single Source     │
                  │   of Truth)         │
                  └─────────┬───────────┘
                            │
                            ▼
                  ┌──────────────────┐
                  │ Grafana Dashboard│
                  └──────────────────┘
```

**Detaillierte Dokumentation** in [`docs/`](docs/):
- `docs/coding_guidelines.md` – Code-Konventionen
- `docs/datenflussarchitektur.md` – Vollständiger Datenfluss, JSON-Schemata, Topics, Formeln
- `docs/pflichtenheft.md` – Technische Systembeschreibung
- `docs/sicherheitskonzept.md` – TLS, ACL, Rollen
- `docs/verkabelung.md` – GPIO-Pinbelegung

---

## Projektstruktur

```
algen-iot/
├── src/
│   ├── algen_iot_core/     ← Zentrale Bibliothek (DRY, von allen Skripten genutzt)
│   └── algen_iot_scripts/  ← Die 10 ausführbaren Skripte
├── tests/                  ← pytest-Tests
├── config.example/         ← Sensor-Konfig-Templates (committed)
├── deploy/
│   ├── systemd/            ← Service-Units
│   └── scripts/            ← Setup-Skripte
├── docs/                   ← Projekt-Dokumentation
├── pyproject.toml          ← Paket-Metadaten + Dependencies
└── .env.example            ← Template für Umgebungsvariablen
```

---

**Goldene Regel:** Alles, was secret ist, kommt **nur** aus Umgebungsvariablen (`INFLUX_TOKEN`, `MQTT_PASSWORD`). Hardcoded Tokens im Code sind in den Coding Guidelines explizit verboten.

---

## Entwicklungs-Workflow

```bash
# Branch erstellen
git checkout -b feature/analyze-algae-vitality

# Code schreiben (folgt Coding Guidelines!)
$EDITOR src/algen_iot_scripts/analyze_algae_vitality.py

# Tests schreiben
$EDITOR tests/test_analyze_algae_vitality.py

# Lokal verifizieren
pytest tests/ -v
ruff check src/ tests/
mypy src/

# Commit + Push
git add .
git commit -m "feat: analyze_algae_vitality nach Datenflussarch. 3.2"
git push origin feature/analyze-algae-vitality

# Pull Request öffnen -> CI läuft automatisch -> Review -> Merge
```

---

## Voraussetzungen

| Komponente | Version |
|---|---|
| Python | 3.11+ |
| Raspberry Pi | 4 oder 5 (8 GB RAM empfohlen für Grafana + InfluxDB lokal) |
| InfluxDB | v2.7+ |
| Mosquitto | 2.0+ mit TLS |
| Grafana | 10.0+ |

---

## License

MIT – siehe [LICENSE](LICENSE).
