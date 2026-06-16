# Algen-IoT – Vollständige Skript-Sammlung

> Alle 10 produktiven Skripte des Photobioreaktor-Systems, vollständig spec-konform implementiert.
> Aufbauend auf der Bibliothek `algen_iot_core`.

---

## Das System auf einen Blick

```
                        ┌─────────────────────────────────┐
                        │      MQTT-Broker (Mosquitto)    │
                        │       TLS, Port 8883            │
                        └─────────────────────────────────┘
                            ▲          ▲           ▲
                            │          │           │
   ┌────────────────────────┼──────────┼───────────┼────────────────────┐
   │                        │          │           │                    │
   ▼                        │          │           │                    ▼
┌─────────────────────┐     │          │           │       ┌──────────────────────┐
│ capture_reactor_    │     │          │           │       │ capture_room_        │
│ sensors.py          │     │          │           │       │ climate.py           │
│ (alle 30s)          │     │          │           │       │ (alle 60s)           │
└──────────┬──────────┘     │          │           │       └──────────┬───────────┘
           │                │          │           │                  │
           │ schreibt       │ alarmiert│           │ alarmiert        │ schreibt
           ▼                │          │           │                  ▼
    ┌─────────────┐         │          │           │            ┌─────────────┐
    │  algen_bio  │         │          │           │            │  algen_bio  │
    │ (InfluxDB)  │         │          │           │            │ (InfluxDB)  │
    └──────┬──────┘         │          │           │            └──────┬──────┘
           │                │          │           │                   │
           │ liest          │          │           │             liest │
           ▼                │          │           │                   ▼
┌─────────────────────┐     │          │           │       ┌──────────────────────┐
│ analyze_algae_      │     │          │           │       │ analyze_air_         │
│ vitality.py         │◄────┘          │           │       │ quality.py           │◄──┐
│ (alle 300s)         │ Alarm-Trigger  │           │       │ (alle 300s)          │   │
└──────────┬──────────┘                │           │       └──────────┬───────────┘   │
           │ schreibt                  │           │                  │ schreibt      │ Alarm-
           ▼                           │           │                  ▼               │ Trigger
    ┌─────────────┐                    │           │            ┌─────────────┐       │
    │  algen_bio  │                    │           │            │  algen_bio  │       │
    └──────┬──────┘                    │           │            └──────┬──────┘       │
           │                           │           │                   │              │
           └──────────┬────────────────┘           │                   │              │
                      │ beide lesen                │                   │              │
                      ▼                            │                   │              │
            ┌─────────────────────┐                │                   │              │
            │ control_actuator_   │                │                   │              │
            │ logic.py            │ ───────────────┼─── cmd ───────────┼──┐           │
            │ (alle 300s)         │                │                   │  │           │
            └─────────────────────┘                │                   │  │           │
                                                   │                   │  ▼           │
                                                   │                   │ ┌────────────────────┐
                                                   │                   │ │ capture_hardware_  │
                                                   │                   │ │ actuators.py       │
                                                   │                   │ │ (event-driven)     │
                                                   │                   │ └─────────┬──────────┘
                                                   │                   │           │ GPIO
                                                   │                   │           ▼
                                                   │                   │   ┌────────────┐
                                                   │                   │   │ Heater     │
                                                   │                   │   │ Pump       │
                                                   │                   │   │ LED (PWM)  │
                                                   │                   │   └────────────┘
                                                   │                   │ status
                                                   │   ┌───────────────┼───┘
                                                   │   ▼               │
                              ┌────────────────────────────────────────┐
                              │ bridge_andanalyse_mqtt_actuator_       │
                              │ status.py                              │
                              │ (Watchdog alle 2s, 5000ms-Timeout)     │
                              └─────┬──────────────────────────────────┘
                                    │ schreibt                          
                                    ▼                                    
                              ┌─────────────┐                            
                              │ algen_system│                            
                              │ (InfluxDB)  │                            
                              └─────┬───────┘                            
                                    │ liest                              
                                    ▼                                    
                              ┌─────────────────────┐ ─────┐             
                              │ bridge_db_to_       │      │             
                              │ dashboard.py        │      │             
                              │ (alle 300s)         │      │             
                              └─────────────────────┘      │             
                                                          ▼              
                                              ┌──────────────────────┐   
                                              │ Grafana / Dashboard  │
                                              └──────────────────────┘
                                                                         
                              ┌─────────────────────┐                    
                              │ bridge_dashboard_   │                    
                              │ alerts.py           │── retain → Dashboard 
                              │ (event-driven)      │                    
                              └─────────────────────┘                    
                                                                         
                              ┌─────────────────────┐                    
                              │ notify_email_       │                    
                              │ service.py          │── SMTP → Admin     
                              │ (event-driven)      │                    
                              └─────────────────────┘                    
```

---

## Übersicht der 10 Skripte

| Skript | Typ | Intervall | Aufgabe |
|---|---|---|---|
| `capture_reactor_sensors.py` | Daemon | 30s | Liest Reaktor-Sensoren (water_temp, ph, turbidity, light_intensity) → InfluxDB. Alarmiert bei Abweichungen. |
| `capture_room_climate.py` | Daemon | 60s | Liest Raumluft-Sensoren (co2, voc, air_temp, humidity) → InfluxDB. Alarmiert bei Abweichungen. |
| `capture_hardware_actuators.py` | Daemon | event-driven | Empfängt MQTT-Befehle, steuert GPIO (Heater/Pump/LED-PWM), meldet jeden State. |
| `analyze_algae_vitality.py` | Daemon | 300s | Berechnet `vitality_score` + `growth_status` aus den letzten 300s Reaktor-Daten. Vergleicht Trübung mit vorherigem Fenster. |
| `analyze_air_quality.py` | Daemon | 300s | Berechnet `air_quality_index` + `action_recommendation` aus den letzten 300s Raumluft-Daten. |
| `control_actuator_logic.py` | Daemon | 300s | Entscheidet anhand der Analysen, welche Aktoren zu schalten sind. Mit Cooldown-Schutz. |
| `bridge_andanalyse_mqtt_actuator_status.py` | Daemon | event-driven + 2s | Persistiert Aktor-States + Alarme in DB. **Watchdog**: 5000ms-Timeout-Erkennung. |
| `notify_email_service.py` | Daemon | event-driven | Versendet bei kritischen Alarmen E-Mails (mit Anti-Spam-Cooldown). |
| `bridge_db_to_dashboard.py` | Daemon | 300s | Aggregiert aktuellen Systemzustand für Grafana-Dashboard. |
| `bridge_dashboard_alerts.py` | Daemon | event-driven | Leitet Alarme als retained MQTT-Messages an das Frontend weiter. |

---

## Was die Skripte miteinander gemeinsam haben

Alle 10 Skripte folgen demselben Bauplan:

```python
"""Datei-Header mit Zweck, Autor, Datum, Kapitelbezug zur Doku."""

import signal, sys, ...
from algen_iot_core import core_constants, core_database, core_mqtt, ...

_logger = core_logger.get_logger("script_name", log_file_path=...)

# State-Variablen, falls nötig

def helper_function(...): ...

def main() -> int:
    # Signal-Handler registrieren (SIGINT, SIGTERM)
    # Initialisierung
    # Hauptschleife oder MQTT-Loop
    
if __name__ == "__main__":
    sys.exit(main())
```

**Zentrale Eigenschaften:**

- **Keine hardcoded Secrets** – Tokens/Passwörter kommen ausschließlich aus Umgebungsvariablen.
- **Kein `print()`** – ausschließlich `core_logger.get_logger()`.
- **Spec-konforme MQTT-Topics** – alle über `core_constants.TOPIC_TEMPLATE_*`.
- **Korrekte Bucket-Routing** – `core_database.db_insert_record()` wählt automatisch zwischen `algen_bio` (90d) und `algen_system` (30d).
- **Saubere Shutdown-Logik** – SIGINT/SIGTERM lösen geordnetes Aufräumen aus (GPIO, MQTT, DB).
- **Robuste Hauptschleifen** – jede Schleife fängt unerwartete Exceptions ab, damit ein einzelner Fehler nicht das ganze Skript stoppt.

---

## Spec-Konformität pro Skript

Jedes Skript erfüllt die in `Coding_Guidelines.md` und `Datenflussarchitektur_und_Datenstrukturen.md` definierten Anforderungen. Im Detail:

### `capture_reactor_sensors.py` ↔ Datenflussarchitektur 3.1.1
- ✅ Liest in der `core_constants.READ_INTERVAL_REAKTOR_S` (30s) Taktung
- ✅ Validiert jeden Sensorwert über `core_hardware.validate_sensor_data()`
- ✅ Schreibt JSON-Standard via `core_utils.build_standard_json()` in `MEASUREMENT_REACTOR_SENSORS`
- ✅ Publiziert Alarme auf `pbr/reactor-01/alarm/sensor/<sensor>` bei Abweichungen
- ✅ Schaltet Sensor bei `sensor_error` stromlos (Kurzschlussschutz)

### `analyze_algae_vitality.py` ↔ Datenflussarchitektur 4.2.1.B
- ✅ Korrekte Strafformel `P = |X/M − 1| × S × 100` über `core_math.calculate_penalty_points()`
- ✅ Wachstumsrate über `core_math.calculate_growth_rate()` mit Vergleich zum Vorgängerfenster
- ✅ `growth_status`-Mapping über `core_math.map_growth_rate_to_status()` (Schwellwerte 2 %, −2 %, −10 %)
- ✅ Emergency-Modus über MQTT-Alarm-Subscription
- ✅ JSON gemäß Spec mit `details`-Wrapper, `analysis_id`, `is_emergency_run`

### `analyze_air_quality.py` ↔ Datenflussarchitektur 4.2.1.A
- ✅ Alle 4 Variablen (co2, voc, air_temp, humidity) werden bewertet
- ✅ Status-Faktor S aus `core_math.get_status_factor()`
- ✅ Korrekte QS-Bereiche (excellent/good/fair/poor/critical) über `map_index_to_quality_label()`
- ✅ Spec-konforme Empfehlungen über `map_quality_to_recommendation()`, inkl. Sonderregeln CO₂<300 und sensor_error→check_sensors
- ✅ **Behebt alle 12 P1-Fehler des Original-Skripts**

### `capture_hardware_actuators.py` ↔ Datenflussarchitektur 3.4 + 4.3/4.4
- ✅ Topic `pbr/reactor-01/actuator/<actuator>/cmd` (Wildcard `+`)
- ✅ State-Maschine accepted → running → completed/error (keine erfundenen States)
- ✅ Pumpenzyklus mit `threading.Event` für Notabbruch
- ✅ Bei Hardware-Fehler: zusätzlich `pbr/reactor-01/alarm/actuator/<actuator>` mit `is_critical=true`
- ✅ Spec-konformes JSON: `action_id`, `actuator`, `state`, `error_details`, `error_code`

### `control_actuator_logic.py` ↔ Datenflussarchitektur 3.3 + 4.3
- ✅ Liest die jüngsten Analysen (Luft + Algen) aus der DB
- ✅ Cooldown-Logik per `COOLDOWN_PERIOD_S` und identischem `is_action_on`-Wert (Hysterese)
- ✅ Generiert `action_id` über `core_utils.generate_uuid()`
- ✅ Loggt jeden Befehl in `MEASUREMENT_ACTUATOR_COMMANDS`
- ✅ Reagiert auf kritische Sensor-Alarme mit Sofort-Zyklus

### `bridge_andanalyse_mqtt_actuator_status.py` ↔ Datenflussarchitektur 3.5.2
- ✅ **Watchdog `check_active_timeouts()`** – das fehlte in allen drei Vorgängerskripten!
- ✅ Läuft alle 2s und prüft 5000ms-Timeout
- ✅ Bei Timeout: DB-Update auf state="timeout", MQTT-Alarm, Alarm-Eintrag mit `ui_status="unresolved"`
- ✅ Konsolidiert die drei Vorgänger-Bridges in EIN Skript

### `notify_email_service.py` ↔ Datenflussarchitektur 3.6
- ✅ Filtert auf `is_critical=true` oder `alert_level="critical"`
- ✅ Anti-Spam-Cooldown pro (device, component, error_code)
- ✅ SMTP-Versand mit STARTTLS, alle Credentials aus Env-Variablen
- ✅ Protokolliert jeden Versand in `MEASUREMENT_NOTIFICATIONS`

### `bridge_db_to_dashboard.py` ↔ Datenflussarchitektur 3.7
- ✅ Aggregiert alle 300s den Systemzustand in `MEASUREMENT_DASHBOARD_AGGREGATES`
- ✅ Grafana kann mit einer einzigen Query alle Werte für das Dashboard ziehen

### `bridge_dashboard_alerts.py` ↔ Datenflussarchitektur 3.7
- ✅ Mapping alert_level → display_type (critical→modal, warning→toast, info→inline)
- ✅ Mapping alert_level → toast_color (error_red, warning_orange, info_blue)
- ✅ Retained MQTT-Message, damit das Frontend nach Reconnect den letzten Alarm sofort sieht

---

## Datenflussbeispiel: Vom Sensor zum Alarm

Konkretes Szenario: Der CO₂-Sensor misst 1.500 ppm (Status: error).

1. **`capture_room_climate.py`** liest CO₂ = 1500, validiert → `co2_status = "error"`
   - Schreibt Datensatz in `MEASUREMENT_ROOM_SENSORS` (Bucket `algen_bio`)
   - Publiziert Alarm auf `pbr/roomnode-01/alarm/sensor/co2` mit `is_critical=true`

2. **`analyze_air_quality.py`** empfängt den Alarm
   - Setzt `_is_emergency_run = True`, weckt die Schleife auf
   - Aggregiert die letzten 300s (CO₂-Mittelwert ist hoch, Status error)
   - Berechnet Strafpunkte (mit S=2 für error), Quality-Index niedrig → "poor"
   - `action_recommendation = "clean_air_more"`
   - Schreibt Analyse-Eintrag in `MEASUREMENT_ANALYSIS_AIR`

3. **`control_actuator_logic.py`** liest die neueste Analyse
   - `action_recommendation == "clean_air_more"` → `decide_pump()` empfiehlt Pumpe für 20s
   - Cooldown-Check: zuletzt vor 30 min Pumpe angeschaltet? → ja, also unterdrücken
     ODER nein → senden
   - Falls senden: generiert `action_id`, publiziert auf `pbr/reactor-01/actuator/pump/cmd`
   - Loggt in `MEASUREMENT_ACTUATOR_COMMANDS`

4. **`capture_hardware_actuators.py`** empfängt den Befehl
   - Validiert, publiziert `accepted` → schaltet GPIO 17 HIGH → publiziert `running`
   - Wartet 20s in `_pump_cycle()` (mit Cancel-Event-Schutz)
   - Schaltet GPIO 17 LOW → publiziert `completed`

5. **`bridge_andanalyse_mqtt_actuator_status.py`** verfolgt alle States
   - Persistiert `accepted` → `running` → `completed` in `MEASUREMENT_ACTUATOR_STATUS`
   - Watchdog hat zwischendurch nichts zu tun, weil die Pumpe rechtzeitig fertig wird
   - Wäre die Pumpe nach 5s noch im State `running`, würde der Watchdog die Aktion als `timeout` markieren und einen Alarm auslösen

6. **`notify_email_service.py`** und **`bridge_dashboard_alerts.py`** haben den ursprünglichen CO₂-Alarm (Schritt 1) gesehen und parallel:
   - E-Mail an Admin/Operator gesendet (mit Anti-Spam-Cooldown)
   - Modal-Popup-Info via `dashboard/alerts` retain-Topic an das Dashboard geschickt

7. **`bridge_db_to_dashboard.py`** läuft alle 300s und aggregiert den aktuellen Zustand
   - `MEASUREMENT_DASHBOARD_AGGREGATES` enthält jetzt einen Snapshot mit `unresolved_alarms = 1`
   - Grafana zeigt den Wert in einer Single-Stat-Panel an

---

## Voraussetzungen

```bash
pip install paho-mqtt influxdb-client RPi.GPIO

# Umgebungsvariablen setzen (z. B. /etc/algen_iot/algen.env)
export INFLUX_URL="http://localhost:8086"
export INFLUX_TOKEN="..."
export INFLUX_ORG="algen_iot"
export MQTT_HOST="localhost"
export MQTT_PORT="8883"
export MQTT_USERNAME="pi_logic"
export MQTT_PASSWORD="..."
export MQTT_TLS_CA="/etc/iot/certs/ca.crt"
export SMTP_HOST="smtp.example.com"
export SMTP_USERNAME="..."
export SMTP_PASSWORD="..."
export SMTP_TO_ADMIN="admin@example.com"
```

## Start der Skripte

Via systemd (siehe `deploy/systemd/` im Repo):
```bash
sudo systemctl enable --now algen-capture-reactor
sudo systemctl enable --now algen-capture-room
sudo systemctl enable --now algen-capture-actuators
sudo systemctl enable --now algen-analyze-algae
sudo systemctl enable --now algen-analyze-air
sudo systemctl enable --now algen-control-actuators
sudo systemctl enable --now algen-bridge-actuator
sudo systemctl enable --now algen-notify-email
sudo systemctl enable --now algen-bridge-dashboard
sudo systemctl enable --now algen-bridge-alerts
```

Oder manuell zum Testen:
```bash
pip install -e ".[pi]"
algen-capture-reactor
```
