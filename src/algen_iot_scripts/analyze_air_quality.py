import time
import json
import threading
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
import paho.mqtt.client as mqtt

# === KONSTANTEN & KONFIGURATION ===
ANALYSIS_INTERVAL_S = 300  # 5 Minuten Standard-Intervall
MQTT_BROKER = "localhost"
MQTT_TOPIC_ALARM = "bioreaktor/alarm/status"

INFLUX_URL = "http://localhost:8086"
INFLUX_TOKEN = "DEIN_SUPER_SICHERER_TOKEN"  # Aus der Influx-Einrichtung
INFLUX_ORG = "DEIN_ORGANISATION_NAME"
INFLUX_BUCKET_SOURCE = "chlorella_bio_trends"  # Hier liegen die Rohdaten
INFLUX_BUCKET_TARGET = "system_stats"         # Hier landen die Analyse-Ergebnisse

# Ideale Mittelwerte (M) für das Chlorella-Wachstum
IDEAL_TEMP = 25.0  # °C ist das Optimum für Chlorella
IDEAL_HUMIDITY = 60.0  # %

# Gewichtungsfaktoren (w) für die Strafpunkte
WEIGHT_TEMP = 5.0  # Temperaturabweichungen sind kritisch

# === GLOBALE VARIABLEN ===
is_emergency_run = False
# Dieses Event nutzen wir, um das 300s-Warten bei einem Alarm sofort zu unterbrechen
change_event = threading.Event()

# === INFLUXDB CLIENT INITIALISIERUNG ===
db_client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
write_api = db_client.write_api(write_options=SYNCHRONOUS)
query_api = db_client.query_api()

# === HILFSFUNKTIONEN ===

def db_get_latest_sensors(seconds=300):
    """Holt die Rohdaten der letzten X Sekunden aus der InfluxDB."""
    flux_query = f'''
    from(bucket: "{INFLUX_BUCKET_SOURCE}")
      |> range(start: -{seconds}s)
      |> filter(fn: (r) => r["_measurement"] == "bioreaktor_sensoren")
      |> filter(fn: (r) => r["_field"] == "temperature_c" or r["_field"] == "humidity_percent")
    '''
    result = query_api.query(flux_query)
    
    # Daten nach Feldern sortieren
    data = {"temperature": [], "humidity": []}
    for table in result:
        for record in table.records:
            if record.get_field() == "temperature_c":
                data["temperature"].append(record.get_value())
            elif record.get_field() == "humidity_percent":
                data["humidity"].append(record.get_value())
    return data

def calculate_average(data_list):
    """Berechnet den arithmetischen Mittelwert."""
    if not data_list:
        return None
    return sum(data_list) / len(data_list)

def calculate_penalty_points(avg, ideal, weight):
    """Strafformel: P = w * (X_quer - M)^2"""
    if avg is None:
        return 0
    return weight * ((avg - ideal) ** 2)

def calculate_score(aggregated_data):
    """Kernfunktion: Berechnet den Luftqualitäts-Score (0-100)."""
    avg_temp = aggregated_data.get("avg_temp")
    avg_hum = aggregated_data.get("avg_humidity")
    
    penalty_temp = calculate_penalty_points(avg_temp, IDEAL_TEMP, WEIGHT_TEMP)
    # Luftfeuchtigkeit wird hier linear/schwächer bestraft
    penalty_hum = abs(avg_hum - IDEAL_HUMIDITY) * 0.5 if avg_hum else 0
    
    total_penalty = penalty_temp + penalty_hum
    score = max(0.0, min(100.0, 100.0 - total_penalty))
    return round(score, 2)

def evaluate_air_quality(score):
    """Ordnet den Score den QS-Breiten zu."""
    if score >= 90.0: return "excellent"
    elif score >= 71.0: return "good"
    elif score >= 50.0: return "warning"
    else: return "critical"

def determine_recommendation(aqi, aggregated_data):
    """Setzt die Prioritäten-Matrix um."""
    avg_temp = aggregated_data.get("avg_temp")
    
    if aqi == "critical":
        return "CRITICAL: Kuehlung aktivieren, Luftzufuhr drosseln!"
    elif aqi == "warning" and avg_temp > 30.0:
        return "WARNUNG: Temperatur hoch. Belueftung erhoehen."
    # Harte Sonderregel aus der Doku
    elif avg_temp and avg_temp > 40.0:
        return "NOTFALL-WARNUNG: Sensor-Fehlfunktion vermutet -> check_sensors"
    else:
        return "System stabil. Keine Aktion erforderlich."

def db_insert_record(payload):
    """Schreibt das fertige Analyse-Ergebnis zurück in die InfluxDB."""
    point = Point("luft_analyse_ergebnis") \
        .tag("air_quality_index", payload["aqi"]) \
        .field("score", payload["score"]) \
        .field("avg_temperature", payload["avg_temp"]) \
        .field("avg_humidity", payload["avg_humidity"]) \
        .field("recommendation", payload["recommendation"]) \
        .field("emergency_run", payload["is_emergency_run"])
    
    write_api.write(bucket=INFLUX_BUCKET_TARGET, org=INFLUX_ORG, record=point)
    print(f"[DB] Analyse-Ergebnis erfolgreich gespeichert. Score: {payload['score']}")

# === MQTT CALLBACKS ===

def on_alarm_received(client, userdata, msg):
    """MQTT-Callback: Wird bei eingehendem Sensor-Alarm aufgerufen."""
    global is_emergency_run
    print(f"\n🚨 [MQTT ALARM] Nachricht empfangen auf {msg.topic}!")
    
    try:
        payload = json.loads(msg.payload.decode())
        # Pruefen, ob der Alarm fuer dieses Skript relevant ist (Luft/Temperatur)
        if "air_temp" in str(payload) or "status" in str(payload):
            is_emergency_run = True
            # Unterbricht das Warten in der Hauptschleife sofort!
            change_event.set()
    except Exception as e:
        print(f"Fehler beim Parsen der Alarm-Nachricht: {e}")

# === HAUPTSCHLEIFE (MAIN LOOP) ===

def main_analysis_loop():
    global is_emergency_run
    print("🚀 Analyse-Skript für Luftqualität gestartet. Warte auf Daten...")
    
    while True:
        # Warten: Entweder 300 Sekunden ODER bis das change_event durch einen Alarm ausgelöst wird
        timeout_occurred = not change_event.wait(timeout=ANALYSIS_INTERVAL_S)
        
        # Event direkt wieder zuruecksetzen fuer den naechsten Durchlauf
        change_event.clear()
        
        print(f"\n--- Analyse-Durchlauf gestartet (Emergency Mode: {is_emergency_run}) ---")
        
        # 1. Datenabruf & Aggregation (bei Notfall kuerzerer Zeitraum sinnvoll)
        time_frame = 60 if is_emergency_run else 300
        raw_data = db_get_latest_sensors(seconds=time_frame)
        
        aggregated_data = {
            "avg_temp": calculate_average(raw_data["temperature"]),
            "avg_humidity": calculate_average(raw_data["humidity"])
        }
        
        # Falls keine Daten vorhanden sind (z.B. Systemausfall)
        if aggregated_data["avg_temp"] is None:
            print("⚠️ Keine Sensordaten in der DB gefunden. Überspringe Durchlauf.")
            is_emergency_run = False
            continue
            
        # 2. Zustandsbewertung
        score = calculate_score(aggregated_data)
        aqi = evaluate_air_quality(score)
        recommendation = determine_recommendation(aqi, aggregated_data)
        
        # 3. Ergebnis-JSON bauen
        analysis_result = {
            "score": score,
            "aqi": aqi,
            "avg_temp": round(aggregated_data["avg_temp"], 2),
            "avg_humidity": round(aggregated_data["avg_humidity"], 2),
            "recommendation": recommendation,
            "is_emergency_run": is_emergency_run
        }
        
        # 4. In Datenbank speichern
        db_insert_record(analysis_result)
        
        # Notfallmodus nach Verarbeitung wieder zuruecksetzen
        if is_emergency_run:
            is_emergency_run = False

# === SKRIPT-START ===
if __name__ == "__main__":
    # MQTT Setup
    mqtt_client = mqtt.Client()
    mqtt_client.on_message = on_alarm_received
    
    try:
        mqtt_client.connect(MQTT_BROKER, 1883, 60)
        mqtt_client.subscribe(MQTT_TOPIC_ALARM)
        # MQTT in eigenem Thread starten, damit es asynchron lauscht
        mqtt_client.loop_start()
    except Exception as e:
        print(f"❌ MQTT Broker Verbindung fehlgeschlagen: {e}. Notfall-Modus deaktiviert.")

    # Hauptschleife starten
    try:
        main_analysis_loop()
    except KeyboardInterrupt:
        print("\n👋 Skript durch Nutzer beendet.")
        mqtt_client.loop_stop()
        db_client.close()