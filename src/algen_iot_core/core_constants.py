"""
core_constants.py - Algen-IoT
=============================

Zentrale Sammlung aller systemweiten Konstanten, Grenzwerte, Topic-Templates,
Idealwerte und Enum-Werte des Photobioreaktor-Systems.

Diese Datei ersetzt die Streuung von Magic Numbers und unterschiedlichen
Bucket-/Org-/Topic-Schemata über alle Skripte hinweg. Alle Skripte importieren
Konstanten ausschliesslich von hier.

Bezieht sich auf:
- Coding Guidelines, Kapitel 3 (Variablen- und Konstanten-Regelungen)
- Datenflussarchitektur und Datenstrukturen, Kapitel 4.1.3 (Grenzwerte),
  Kapitel 4.2 (Analyse-Logik), Kapitel 5 (Taktungsprotokoll)
- Pflichtenheft 5.1 (Retention), 6.3 (Sicherheit), 7.1 (Hardware-Schnittstellen)

Autor: Algen-IoT Team
Datum: 2026-05-31
"""

# ============================================================================
# 1. SYSTEM-IDENTIFIKATION
# ============================================================================

REACTOR_DEVICE_ID = "reactor-01"
"""ID des Reaktor-Knotens (Wassersensorik + Aktorik)."""

ROOMNODE_DEVICE_ID = "roomnode-01"
"""ID des Raumluft-Knotens (Umgebungssensorik)."""


# ============================================================================
# 2. TAKTUNGSINTERVALLE (Datenflussarch. Kapitel 5)
# ============================================================================

READ_INTERVAL_REAKTOR_S = 30
"""Sensorerfassung Reaktor in Sekunden (Datenflussarch. 3.1.2)."""

READ_INTERVAL_AIR_S = 60
"""Sensorerfassung Raumluft in Sekunden (Datenflussarch. 3.1.2)."""

ANALYSIS_INTERVAL_S = 300
"""Analyse-Intervall fuer Algen- und Luftbewertung (Datenflussarch. 3.2.2)."""

DASHBOARD_REFRESH_INTERVAL_S = 300
"""Dashboard-Aggregation fuer das Frontend (Datenflussarch. 3.8.2)."""

COOLDOWN_PERIOD_S = 3600
"""Spam-Schutz fuer Email-Versand (Datenflussarch. 3.6.2)."""

ACTUATOR_TIMEOUT_MS = 5000
"""Maximale Zeit fuer Aktor-Rueckmeldung bevor 'timeout' gilt (4.4)."""

MAX_RETRIES = 3
"""Wiederholungsversuche fuer Hardware-Reads und DB-Inserts."""

MAX_LAST_ACTIONS_COUNT = 5
"""Anzahl letzter Aktor-Aktionen im Dashboard-JSON (Datenflussarch. 3.8.2)."""

ALARM_COOLDOWN_INFO_S = 12 * 3600
"""Cooldown info-Alarme: 12 Stunden (Datenflussarch. 4.6)."""

ALARM_COOLDOWN_WARNING_S = 3600
"""Cooldown warning-Alarme: 1 Stunde (Datenflussarch. 4.6)."""

ALARM_COOLDOWN_CRITICAL_S = 3600
"""Cooldown critical-Alarme: 1 Stunde (Datenflussarch. 4.6)."""


# ============================================================================
# 3. MQTT-KONFIGURATION (Pflichtenheft 6.3, Sicherheitskonzept)
# ============================================================================

MQTT_HOST_DEFAULT = "localhost"
"""Standard-Host des Mosquitto-Brokers."""

MQTT_PORT_TLS = 8883
"""TLS-Port fuer MQTTS (Pflichtenheft 6.3)."""

MQTT_PORT_PLAIN = 1883
"""Klartext-Port - NUR fuer lokale Tests, NICHT fuer Produktivbetrieb."""

MQTT_QOS_AT_LEAST_ONCE = 1
"""QoS Level 1 (At least once delivery) - MoSCoW Must-Have."""

MQTT_USER_LOGIC = "pi_logic"
"""Schreibender MQTT-Benutzer fuer interne Skripte (Sicherheitskonzept)."""

MQTT_USER_READER = "reader_user"
"""Lesender MQTT-Benutzer fuer Dashboard (Sicherheitskonzept)."""

MQTT_KEEPALIVE_S = 60
"""MQTT-Keepalive-Intervall in Sekunden."""


# ============================================================================
# 4. MQTT-TOPIC-TEMPLATES (Pflichtenheft 4.5.2, Datenflussarch. 3.5/4.x)
# ============================================================================

TOPIC_TEMPLATE_ACTUATOR_CMD = "pbr/{device_id}/actuator/{actuator_name}/cmd"
"""Topic fuer Aktor-Stellbefehle. Beispiel: pbr/reactor-01/actuator/pump/cmd"""

TOPIC_TEMPLATE_ACTUATOR_STATUS = "pbr/{device_id}/actuator/{actuator_name}/status"
"""Topic fuer Aktor-Rueckmeldungen. Beispiel: pbr/reactor-01/actuator/heater/status"""

TOPIC_TEMPLATE_ALARM_SENSOR = "pbr/{device_id}/alarm/sensor/{sensor_name}"
"""Topic fuer Sensor-Alarme. Beispiel: pbr/reactor-01/alarm/sensor/turbidity"""

TOPIC_TEMPLATE_ALARM_ACTUATOR = "pbr/{device_id}/alarm/actuator/{actuator_name}"
"""Topic fuer Aktor-Alarme. Beispiel: pbr/reactor-01/alarm/actuator/pump"""

TOPIC_WILDCARD_ALL_STATUS = "pbr/+/actuator/+/status"
"""Wildcard fuer alle Aktor-Status (Bridge-Skripte)."""

TOPIC_WILDCARD_ALL_ALARMS = "pbr/+/alarm/#"
"""Wildcard fuer alle Alarme (Notification-Skripte)."""


# ============================================================================
# 5. INFLUXDB-KONFIGURATION (Retention Policies, Pflichtenheft 5.1)
# ============================================================================

INFLUX_URL_DEFAULT = "http://localhost:8086"
"""Standard-URL der InfluxDB. Fuer Produktivbetrieb auf https umstellen."""

INFLUX_ORG = "algen_iot"
"""Einheitliche Organisation in InfluxDB (loest bisherigen Bucket-Wildwuchs)."""

INFLUX_BUCKET_BIOLOGY = "algen_bio"
"""Bucket fuer biologische Trends (Retention: 90 Tage, Pflichtenheft 5.1)."""

INFLUX_BUCKET_SYSTEM = "algen_system"
"""Bucket fuer Systemstatistik (Retention: 30 Tage, Pflichtenheft 5.1)."""

INFLUX_RETENTION_BIOLOGY_DAYS = 90
"""Retention biologische Daten in Tagen."""

INFLUX_RETENTION_SYSTEM_DAYS = 30
"""Retention Systemstatistik in Tagen."""


# ============================================================================
# 6. INFLUXDB MEASUREMENT-NAMEN (zentral, statt 3 verschiedene Schemata)
# ============================================================================

MEASUREMENT_REACTOR_SENSORS = "reactor_sensors"
"""Rohdaten der Reaktor-Sensoren (water_temp, ph, turbidity, light_intensity)."""

MEASUREMENT_ROOM_SENSORS = "room_sensors"
"""Rohdaten der Raumluftsensoren (co2, air_temp, humidity, voc)."""

MEASUREMENT_ANALYSIS_ALGAE = "analysis_algae"
"""Ergebnisse der Algenanalyse (growth_status, vitality_score)."""

MEASUREMENT_ANALYSIS_AIR = "analysis_air"
"""Ergebnisse der Luftanalyse (air_quality_index, action_recommendation)."""

MEASUREMENT_ACTUATOR_COMMANDS = "actuator_commands"
"""Vom Logik-Skript versendete Stellbefehle (action_id, actuator, ...)."""

MEASUREMENT_ACTUATOR_STATUS = "actuator_status"
"""Rueckmeldungen der Aktoren (accepted/running/completed/error/timeout)."""

MEASUREMENT_ALARMS = "alarms"
"""Sensor- und Aktor-Alarme inkl. ui_status fuer Dashboard."""

MEASUREMENT_NOTIFICATIONS = "notifications"
"""Versendete Email-/UI-Benachrichtigungen."""

MEASUREMENT_SYSTEM_STATS = "system_stats"
"""CPU/RAM/Watchdog des Raspberry Pi."""


# ============================================================================
# 7. GPIO-PINBELEGUNG (Pflichtenheft 7.1, Verkabelungs-Doku)
# ============================================================================

GPIO_PIN_HEATER = 27
"""GPIO-Pin Heizungs-Relais (BCM-Nummerierung)."""

GPIO_PIN_PUMP = 17
"""GPIO-Pin Pumpen-Relais (BCM)."""

GPIO_PIN_LED_PWM = 18
"""GPIO-Pin LED-PWM (BCM, PWM-faehig)."""

GPIO_PIN_DS18B20 = 4
"""GPIO-Pin DS18B20-Wassertemperatursensor (1-Wire)."""

LED_PWM_FREQUENCY_HZ = 1000
"""PWM-Frequenz fuer LED-Treiber in Hertz."""


# ============================================================================
# 8. SENSOR-LISTEN (fuer Iteration in capture-Skripten)
# ============================================================================

SENSORS_REACTOR = ["water_temp", "ph", "turbidity", "light_intensity"]
"""Liste aller Reaktor-Sensoren (Reihenfolge entspricht JSON-Schema)."""

SENSORS_ROOM = ["co2", "air_temp", "humidity", "voc"]
"""Liste aller Raumluft-Sensoren."""

ACTUATORS = ["heater", "pump", "led"]
"""Liste aller Aktoren (englische Namen, MQTT-Topic-kompatibel)."""


# ============================================================================
# 9. DATEN-STATUS-WERTE (Datenflussarch. 4.1.1/4.1.2)
# ============================================================================

DATA_STATUS_NORMAL = "normal"
DATA_STATUS_WARNING = "warning"
DATA_STATUS_ERROR = "error"
DATA_STATUS_SENSOR_ERROR = "sensor_error"

DATA_STATUS_VALID_VALUES = {
    DATA_STATUS_NORMAL,
    DATA_STATUS_WARNING,
    DATA_STATUS_ERROR,
    DATA_STATUS_SENSOR_ERROR,
}


# ============================================================================
# 10. STATUS-FAKTOREN FUER STRAFFORMEL (Datenflussarch. 4.2.1.A Stufe 2)
# ============================================================================

STATUS_FACTOR_MAP = {
    DATA_STATUS_NORMAL: 0,
    DATA_STATUS_SENSOR_ERROR: 0,
    DATA_STATUS_WARNING: 1,
    DATA_STATUS_ERROR: 2,
}
"""S-Faktor fuer Strafpunkte: P = |X/M - 1| * S * 100."""


# ============================================================================
# 11. SENSORWERT-GRENZEN (Datenflussarch. 4.1.3.B/C)
# ============================================================================

THRESHOLD_VALUES_WATER_TEMP = {
    "unit": "C",
    "normal":       {"min": 28.0,   "max": 32.0},
    "warning_low":  {"min": 20.0,   "max": 28.0},
    "warning_high": {"min": 32.0,   "max": 38.0},
    "error_low":    {"min": -127.0, "max": 20.0},
    "error_high":   {"min": 38.0,   "max": 50.0},
    "sensor_error_value": [-127.0, 85.0],
}
"""Schwellwerte DS18B20 Wassertemperatur."""

THRESHOLD_VALUES_PH = {
    "unit": "pH",
    "normal":       {"min": 6.5,  "max": 8.5},
    "warning_low":  {"min": 5.5,  "max": 6.5},
    "warning_high": {"min": 8.5,  "max": 9.5},
    "error_low":    {"min": 0.0,  "max": 5.5},
    "error_high":   {"min": 9.5,  "max": 14.0},
    "sensor_error_range": {"min": -1.0, "max": 15.0},
}

THRESHOLD_VALUES_TURBIDITY = {
    "unit": "g/l",
    "normal":       {"min": 0.5, "max": 5.0},
    "warning_low":  {"min": 0.1, "max": 0.5},
    "warning_high": {"min": 5.0, "max": 6.0},
    "error_low":    {"min": 0.0, "max": 0.1},
    "error_high":   {"min": 6.0, "max": 99999.0},
}

THRESHOLD_VALUES_LIGHT_INTENSITY = {
    "unit": "lx",
    "normal":       {"min": 5000.0,  "max": 7500.0},
    "warning_low":  {"min": 500.0,   "max": 5000.0},
    "warning_high": {"min": 7500.0,  "max": 12000.0},
    "error_low":    {"min": 0.0,     "max": 500.0},
    "error_high":   {"min": 12000.0, "max": 99999.0},
}

THRESHOLD_VALUES_CO2 = {
    "unit": "ppm",
    "normal":       {"min": 400.0,  "max": 1000.0},
    "warning_low":  {"min": 300.0,  "max": 400.0},
    "warning_high": {"min": 1000.0, "max": 2000.0},
    "error_range":  {"min": 2000.0, "max": 8000.0},
    "sensor_error_low":  {"max": 300.0},
    "sensor_error_high": {"min": 8000.0},
}

THRESHOLD_VALUES_VOC = {
    "unit": "ppb",
    "normal":       {"min": 0.0,   "max": 200.0},
    "warning_high": {"min": 200.0, "max": 800.0},
    "error_high":   {"min": 800.0, "max": 99999.0},
    "sensor_error_low": {"max": 0.0},
}

THRESHOLD_VALUES_AIR_TEMP = {
    "unit": "C",
    "normal":       {"min": 18.0,  "max": 26.0},
    "warning_low":  {"min": 10.0,  "max": 18.0},
    "warning_high": {"min": 26.0,  "max": 35.0},
    "error_low":    {"min": -10.0, "max": 10.0},
    "error_high":   {"min": 35.0,  "max": 60.0},
}

THRESHOLD_VALUES_HUMIDITY = {
    "unit": "%",
    "normal":       {"min": 40.0, "max": 60.0},
    "warning_low":  {"min": 20.0, "max": 40.0},
    "warning_high": {"min": 60.0, "max": 85.0},
    "error_low":    {"min": 0.0,  "max": 20.0},
    "error_high":   {"min": 85.0, "max": 100.0},
}

THRESHOLD_VALUES_MAP = {
    "water_temp":      THRESHOLD_VALUES_WATER_TEMP,
    "ph":              THRESHOLD_VALUES_PH,
    "turbidity":       THRESHOLD_VALUES_TURBIDITY,
    "light_intensity": THRESHOLD_VALUES_LIGHT_INTENSITY,
    "co2":             THRESHOLD_VALUES_CO2,
    "voc":             THRESHOLD_VALUES_VOC,
    "air_temp":        THRESHOLD_VALUES_AIR_TEMP,
    "humidity":        THRESHOLD_VALUES_HUMIDITY,
}
"""Zentraler Zugriff auf alle Sensor-Schwellwerte per Sensorname."""


# ============================================================================
# 12. IDEALWERTE M (Goldene Mitte fuer Strafformel, Datenflussarch. 4.2.1.A Stufe 0)
# ============================================================================

IDEAL_VALUE_WATER_TEMP = 30.0       # (28.0 + 32.0) / 2
IDEAL_VALUE_PH = 7.5                # (6.5 + 8.5) / 2
IDEAL_VALUE_TURBIDITY = 2.75        # (0.5 + 5.0) / 2
IDEAL_VALUE_LIGHT_INTENSITY = 6250  # (5000 + 7500) / 2
IDEAL_VALUE_CO2 = 700               # (400 + 1000) / 2
IDEAL_VALUE_VOC = 100               # (0 + 200) / 2
IDEAL_VALUE_AIR_TEMP = 22.0         # (18.0 + 26.0) / 2
IDEAL_VALUE_HUMIDITY = 50.0         # (40.0 + 60.0) / 2

IDEAL_VALUES_MAP = {
    "water_temp":      IDEAL_VALUE_WATER_TEMP,
    "ph":              IDEAL_VALUE_PH,
    "turbidity":       IDEAL_VALUE_TURBIDITY,
    "light_intensity": IDEAL_VALUE_LIGHT_INTENSITY,
    "co2":             IDEAL_VALUE_CO2,
    "voc":             IDEAL_VALUE_VOC,
    "air_temp":        IDEAL_VALUE_AIR_TEMP,
    "humidity":        IDEAL_VALUE_HUMIDITY,
}


# ============================================================================
# 13. SENSOR-FEHLERWERTE (Datenflussarch. 4.1.3.A)
# ============================================================================

SENSOR_ERROR_RETURN_VALUE = -1.0
"""Rueckgabewert fuer get_sensor_data bei Kommunikationsfehler."""

SENSOR_VALUES_DS18B20_DEFECT = [-127.0, 85.0]
"""Werte, die DS18B20 bei Defekt liefert (Verbindung getrennt o. Pull-up defekt)."""

SENSOR_ADC_MAX_VALUE_10BIT = 1023
"""Maximalwert MCP3008 (10-Bit ADC); 0 oder Maximum deutet auf Kabel-Defekt."""


# ============================================================================
# 14. AIR-QUALITY-INDEX-WERTE (Datenflussarch. 4.2.1.A Stufe 5)
# ============================================================================

AIR_QUALITY_INDEX_EXCELLENT = "excellent"
AIR_QUALITY_INDEX_GOOD = "good"
AIR_QUALITY_INDEX_FAIR = "fair"
AIR_QUALITY_INDEX_POOR = "poor"
AIR_QUALITY_INDEX_CRITICAL = "critical"

AIR_QUALITY_INDEX_VALID_VALUES = {
    AIR_QUALITY_INDEX_EXCELLENT,
    AIR_QUALITY_INDEX_GOOD,
    AIR_QUALITY_INDEX_FAIR,
    AIR_QUALITY_INDEX_POOR,
    AIR_QUALITY_INDEX_CRITICAL,
}

QS_RANGES = [
    # (untere_grenze_inklusiv, label) - sortiert absteigend
    (91, AIR_QUALITY_INDEX_EXCELLENT),
    (71, AIR_QUALITY_INDEX_GOOD),
    (41, AIR_QUALITY_INDEX_FAIR),
    (11, AIR_QUALITY_INDEX_POOR),
    (0,  AIR_QUALITY_INDEX_CRITICAL),
]
"""QS-Bereiche fuer map_index_to_quality_label. Bereiche entsprechen
Datenflussarch. 4.2.1.A Stufe 5: excellent 100-91, good 90-71, fair 70-41,
poor 40-11, critical 10-0."""


# ============================================================================
# 15. ACTION-RECOMMENDATION-WERTE (Datenflussarch. 4.2.1.A Stufe 6)
# ============================================================================

ACTION_RECOMMENDATION_NONE = "none"
ACTION_RECOMMENDATION_CLEAN_MORE = "clean_air_more"
ACTION_RECOMMENDATION_CLEAN_LESS = "clean_air_less"
ACTION_RECOMMENDATION_KEEP_SAME = "keep_air_condition_same"
ACTION_RECOMMENDATION_CHECK_SENSORS = "check_sensors"

ACTION_RECOMMENDATION_VALID_VALUES = {
    ACTION_RECOMMENDATION_NONE,
    ACTION_RECOMMENDATION_CLEAN_MORE,
    ACTION_RECOMMENDATION_CLEAN_LESS,
    ACTION_RECOMMENDATION_KEEP_SAME,
    ACTION_RECOMMENDATION_CHECK_SENSORS,
}

QUALITY_TO_RECOMMENDATION_MAP = {
    AIR_QUALITY_INDEX_EXCELLENT: ACTION_RECOMMENDATION_CLEAN_LESS,
    AIR_QUALITY_INDEX_GOOD:      ACTION_RECOMMENDATION_KEEP_SAME,
    AIR_QUALITY_INDEX_FAIR:      ACTION_RECOMMENDATION_CLEAN_MORE,
    AIR_QUALITY_INDEX_POOR:      ACTION_RECOMMENDATION_CLEAN_MORE,
    AIR_QUALITY_INDEX_CRITICAL:  ACTION_RECOMMENDATION_CLEAN_MORE,
}
"""Mapping Quality-Index -> Empfehlung gemaess Prio-Tabelle 4.2.1.A Stufe 6."""

CO2_SPECIAL_RULE_THRESHOLD = 300.0
"""Sonderregel: CO2 < 300 ppm -> clean_air_less (Datenflussarch. 4.2.1.A)."""

TURBIDITY_SPECIAL_RULE_THRESHOLD = 6.0
"""Sonderregel: Truebung > 6.0 g/l -> clean_air_less."""


# ============================================================================
# 16. GROWTH-STATUS-WERTE (Datenflussarch. 4.2.1.B Stufe 5)
# ============================================================================

GROWTH_STATUS_GROWTH = "growth"
GROWTH_STATUS_STABILITY = "stability"
GROWTH_STATUS_EXTINCTION = "extinction"
GROWTH_STATUS_CONTAMINATION = "contamination_suspected"

GROWTH_STATUS_VALID_VALUES = {
    GROWTH_STATUS_GROWTH,
    GROWTH_STATUS_STABILITY,
    GROWTH_STATUS_EXTINCTION,
    GROWTH_STATUS_CONTAMINATION,
}

GROWTH_RATE_THRESHOLD_GROWTH_PCT = 2.0
"""T > 2% -> growth"""

GROWTH_RATE_THRESHOLD_STABILITY_PCT = 2.0
"""-2% <= T <= 2% -> stability"""

GROWTH_RATE_THRESHOLD_CONTAMINATION_PCT = -10.0
"""T < -10% -> contamination_suspected"""


# ============================================================================
# 17. AKTOR-STATE-WERTE (Datenflussarch. 4.4)
# ============================================================================

ACTUATOR_STATE_ACCEPTED = "accepted"
ACTUATOR_STATE_RUNNING = "running"
ACTUATOR_STATE_COMPLETED = "completed"
ACTUATOR_STATE_ERROR = "error"
ACTUATOR_STATE_TIMEOUT = "timeout"

ACTUATOR_STATE_VALID_VALUES = {
    ACTUATOR_STATE_ACCEPTED,
    ACTUATOR_STATE_RUNNING,
    ACTUATOR_STATE_COMPLETED,
    ACTUATOR_STATE_ERROR,
    ACTUATOR_STATE_TIMEOUT,
}

ACTUATOR_STATE_TERMINAL = {
    ACTUATOR_STATE_COMPLETED,
    ACTUATOR_STATE_ERROR,
    ACTUATOR_STATE_TIMEOUT,
}
"""States, nach denen kein weiterer Status mehr erwartet wird."""


# ============================================================================
# 18. TRIGGER-REASON-WERTE (Datenflussarch. 4.3)
# ============================================================================

TRIGGER_REASON_THRESHOLD = "threshold_exceeded"
TRIGGER_REASON_SCHEDULED = "scheduled_event"
TRIGGER_REASON_SAFETY = "safety_override"
TRIGGER_REASON_MANUAL = "manual_request"

TRIGGER_REASON_VALID_VALUES = {
    TRIGGER_REASON_THRESHOLD,
    TRIGGER_REASON_SCHEDULED,
    TRIGGER_REASON_SAFETY,
    TRIGGER_REASON_MANUAL,
}


# ============================================================================
# 19. AKTOR-WERTBEREICHE (Datenflussarch. 4.3.x)
# ============================================================================

PUMP_DURATION_MIN_S = 1
PUMP_DURATION_MAX_S = 600
"""Pumpen-Laufzeit in Sekunden (Datenflussarch. 4.3.1)."""

HEATER_TARGET_TEMP_MIN = 28
HEATER_TARGET_TEMP_MAX = 32
"""Heizungs-Sollwertbereich (Datenflussarch. 4.3.2)."""

LED_INTENSITY_MIN_PCT = 0
LED_INTENSITY_MAX_PCT = 100
LED_TARGET_LUX_MIN = 5000
LED_TARGET_LUX_MAX = 7500
LED_PHOTOINHIBITION_THRESHOLD_LUX = 14000
"""LED-Wertebereich und Photoinhibitions-Grenzwert (Datenflussarch. 4.3.3 + Pflichtenheft)."""


# ============================================================================
# 20. AKTOR-ERROR-CODES (Datenflussarch. 4.5)
# ============================================================================

ERROR_CODE_HARDWARE_FAULT = "hardware_fault"
ERROR_CODE_TIMEOUT_EXCEEDED = "timeout_exceeded"
ERROR_CODE_INVALID_COMMAND = "invalid_command"

ERROR_CODE_VALID_VALUES = {
    ERROR_CODE_HARDWARE_FAULT,
    ERROR_CODE_TIMEOUT_EXCEEDED,
    ERROR_CODE_INVALID_COMMAND,
}


# ============================================================================
# 21. ALARM-LEVELS UND DASHBOARD-ANZEIGE (Datenflussarch. 4.6 + 4.7)
# ============================================================================

ALERT_LEVEL_INFO = "info"
ALERT_LEVEL_WARNING = "warning"
ALERT_LEVEL_CRITICAL = "critical"

ALERT_LEVEL_VALID_VALUES = {
    ALERT_LEVEL_INFO,
    ALERT_LEVEL_WARNING,
    ALERT_LEVEL_CRITICAL,
}

DELIVERY_STATUS_SENT = "sent"
DELIVERY_STATUS_FAILED = "failed"
DELIVERY_STATUS_QUEUED = "queued"

DISPLAY_TYPE_MODAL = "modal"
DISPLAY_TYPE_TOAST = "toast"
DISPLAY_TYPE_INLINE = "inline"

TOAST_COLOR_ERROR = "error_red"
TOAST_COLOR_WARNING = "warning_orange"
TOAST_COLOR_INFO = "info_blue"

UI_STATUS_UNRESOLVED = "unresolved"
UI_STATUS_RESOLVED = "resolved"


# ============================================================================
# 22. UUID-PRAEFIXE FUER build_standard_json
# ============================================================================

UUID_PREFIX_SENSOR_RECORD = "sens-uuid-"
UUID_PREFIX_AIR_ANALYSIS = "air-analysis-"
UUID_PREFIX_ALGAE_ANALYSIS = "algae-analysis-"
UUID_PREFIX_ACTUATOR_COMMAND = "act-uuid-"
UUID_PREFIX_ALARM = "alrm-uuid-"
UUID_PREFIX_NOTIFICATION = "mail-uuid-"
UUID_PREFIX_DASHBOARD = "dashboard-uuid-"
UUID_PREFIX_UI_NOTIFICATION = "ui-uuid-"


# ============================================================================
# 23. KONFIGURATIONSDATEI-PFADE (Coding Guidelines: CONFIGURATION_FILE_PATH_*)
# ============================================================================

CONFIGURATION_DIR_DEFAULT = "/etc/algen_iot/config"

CONFIGURATION_FILE_PATH_PH = f"{CONFIGURATION_DIR_DEFAULT}/sensor_ph.json"
CONFIGURATION_FILE_PATH_TURBIDITY = f"{CONFIGURATION_DIR_DEFAULT}/sensor_turbidity.json"
CONFIGURATION_FILE_PATH_WATER_TEMP = f"{CONFIGURATION_DIR_DEFAULT}/sensor_water_temp.json"
CONFIGURATION_FILE_PATH_CO2 = f"{CONFIGURATION_DIR_DEFAULT}/sensor_co2.json"
CONFIGURATION_FILE_PATH_VOC = f"{CONFIGURATION_DIR_DEFAULT}/sensor_voc.json"
CONFIGURATION_FILE_PATH_AIR_TEMP = f"{CONFIGURATION_DIR_DEFAULT}/sensor_air_temp.json"
CONFIGURATION_FILE_PATH_HUMIDITY = f"{CONFIGURATION_DIR_DEFAULT}/sensor_humidity.json"
CONFIGURATION_FILE_PATH_LIGHT_INTENSITY = f"{CONFIGURATION_DIR_DEFAULT}/sensor_light_intensity.json"

CONFIGURATION_FILE_PATH_MAP = {
    "ph":              CONFIGURATION_FILE_PATH_PH,
    "turbidity":       CONFIGURATION_FILE_PATH_TURBIDITY,
    "water_temp":      CONFIGURATION_FILE_PATH_WATER_TEMP,
    "co2":             CONFIGURATION_FILE_PATH_CO2,
    "voc":             CONFIGURATION_FILE_PATH_VOC,
    "air_temp":        CONFIGURATION_FILE_PATH_AIR_TEMP,
    "humidity":        CONFIGURATION_FILE_PATH_HUMIDITY,
    "light_intensity": CONFIGURATION_FILE_PATH_LIGHT_INTENSITY,
}


# ============================================================================
# 24. LOGGING & DEBUG (Coding Guidelines Kapitel 5)
# ============================================================================

IS_DEBUG_MODE_ENABLED = False
"""Globales Debug-Flag. Im Produktivbetrieb auf False, im Entwicklungsmodus True."""

LOG_DIRECTORY_DEFAULT = "/var/log/algen_iot"
LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
