"""
core_database.py - Algen-IoT
============================

Zentrale Datenbank-Abstraktionsschicht fuer InfluxDB v2.

WICHTIG zur InfluxDB-Terminologie: Die Coding Guidelines verwenden den
Begriff "table_name", InfluxDB v2 kennt aber keine Tabellen. Diese
Bibliothek interpretiert "table_name" konsequent als "measurement_name"
(siehe core_constants.MEASUREMENT_*). Der Bucket wird automatisch
aus dem Measurement-Namen abgeleitet:
- analysis_*, *_sensors                  -> INFLUX_BUCKET_BIOLOGY (90d)
- actuator_*, alarms, notifications, *_system_stats -> INFLUX_BUCKET_SYSTEM (30d)

Credentials werden ausschliesslich aus Umgebungsvariablen geladen
(Sicherheitskonzept, Pflichtenheft 6.3). Hardcoded Tokens sind verboten.

Bezieht sich auf:
- Coding Guidelines, Kapitel 3 (core_database.py - erweiterte Liste)
- Datenflussarchitektur und Datenstrukturen, Kapitel 3 (alle DB-Zugriffe)
- Pflichtenheft 5.1 (InfluxDB), Retention-Policies-Doku

Autor: Algen-IoT Team
Datum: 2026-05-31
"""

import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.exceptions import InfluxDBError
from influxdb_client.client.write_api import SYNCHRONOUS

from algen_iot_core import core_constants
from algen_iot_core import core_logger


_logger = core_logger.get_logger("core_database")


# ============================================================================
# CLIENT-SINGLETON (eine Verbindung pro Prozess)
# ============================================================================

_influx_client: Optional[InfluxDBClient] = None
_write_api = None
_query_api = None


def _load_token_from_env() -> str:
    """Liest INFLUX_TOKEN aus den Umgebungsvariablen.

    Returns:
        str: Token. Leerer String, wenn nicht gesetzt (-> Verbindung schlaegt
            spaeter fehl, aber wir vermeiden hardcoded Defaults).

    Raises:
        RuntimeError: Wenn die Umgebungsvariable fehlt und ein
            Schreib-/Lesezugriff erfolgt.
    """
    token = os.getenv("INFLUX_TOKEN", "")
    if not token:
        raise RuntimeError(
            "Umgebungsvariable INFLUX_TOKEN ist nicht gesetzt. "
            "Hardcoded Tokens sind laut Sicherheitskonzept verboten."
        )
    return token


def _get_client() -> InfluxDBClient:
    """Lazy-Initialisierung des Influx-Clients (Singleton).

    Returns:
        InfluxDBClient: Bereiter Client.
    """
    global _influx_client, _write_api, _query_api
    if _influx_client is None:
        url = os.getenv("INFLUX_URL", core_constants.INFLUX_URL_DEFAULT)
        org = os.getenv("INFLUX_ORG", core_constants.INFLUX_ORG)
        token = _load_token_from_env()
        _influx_client = InfluxDBClient(url=url, token=token, org=org, timeout=10_000)
        _write_api = _influx_client.write_api(write_options=SYNCHRONOUS)
        _query_api = _influx_client.query_api()
        _logger.info("InfluxDB-Client initialisiert (url=%s, org=%s).", url, org)
    return _influx_client


def close() -> None:
    """Schliesst die DB-Verbindung sauber (am Skriptende aufrufen)."""
    global _influx_client, _write_api, _query_api
    if _influx_client is not None:
        try:
            _influx_client.close()
        except Exception as exc:
            _logger.warning("Influx-Close-Fehler: %s", exc)
    _influx_client = None
    _write_api = None
    _query_api = None


# ============================================================================
# BUCKET-AUFLOESUNG (zentral, statt 4 verschiedene Schemata in Skripten)
# ============================================================================

_BIOLOGY_MEASUREMENTS = {
    core_constants.MEASUREMENT_REACTOR_SENSORS,
    core_constants.MEASUREMENT_ROOM_SENSORS,
    core_constants.MEASUREMENT_ANALYSIS_ALGAE,
    core_constants.MEASUREMENT_ANALYSIS_AIR,
}


def _resolve_bucket(measurement_name: str) -> str:
    """Ordnet Measurement -> richtigem Bucket zu.

    Biologische Daten landen im 90-Tage-Bucket, alles andere im 30-Tage.
    Damit ist die Retention Policy aus Pflichtenheft 5.1 automatisch
    eingehalten und kein Skript kann mehr versehentlich in den falschen
    Bucket schreiben (vorhandener Bug in analyze_air_quality.py).

    Args:
        measurement_name: Einer aus core_constants.MEASUREMENT_*.

    Returns:
        str: Bucket-Name.
    """
    if measurement_name in _BIOLOGY_MEASUREMENTS:
        return core_constants.INFLUX_BUCKET_BIOLOGY
    return core_constants.INFLUX_BUCKET_SYSTEM


# ============================================================================
# 1. INSERT (Coding Guidelines core_database.py)
# ============================================================================

def db_insert_record(table_name: str,
                     json_payload: dict,
                     extra_tags: Optional[dict] = None) -> bool:
    """Schreibt einen Datensatz als InfluxDB-Point.

    Fuehrt automatisch Retries durch (MAX_RETRIES) bei Netzwerkfehlern
    oder kurzfristigen DB-Blockaden, wie in Coding Guidelines spezifiziert.

    Konvention zur Tag/Field-Trennung:
    - Tags  : alle Schluessel, die mit "_id" enden (device_id, action_id, ...)
              + sensor_name, actuator, state, severity, ...
              + Inhalte aus extra_tags
    - Fields: alle uebrigen Werte. Floats werden als float gespeichert,
              ints als int, Strings als str. Nested dicts werden als
              JSON-String serialisiert.

    Args:
        table_name: Measurement-Name (siehe core_constants.MEASUREMENT_*).
        json_payload: Das standardisierte JSON-Objekt aus
            core_utils.build_standard_json().
        extra_tags: Zusaetzliche Tag-Namen.

    Returns:
        bool: True, wenn der Eintrag innerhalb von MAX_RETRIES geschrieben
        werden konnte.
    """
    try:
        _get_client()
    except RuntimeError as exc:
        _logger.error("db_insert_record: %s", exc)
        return False

    point = _build_point(table_name, json_payload, extra_tags or {})
    bucket = _resolve_bucket(table_name)

    for attempt in range(1, core_constants.MAX_RETRIES + 1):
        try:
            _write_api.write(bucket=bucket, record=point)
            _logger.info("Insert ok [bucket=%s, measurement=%s, try=%d].",
                          bucket, table_name, attempt)
            return True
        except (InfluxDBError, OSError) as exc:
            _logger.warning("Insert-Versuch %d/%d fehlgeschlagen: %s",
                             attempt, core_constants.MAX_RETRIES, exc)
            time.sleep(0.5 * attempt)

    _logger.error("Insert nach %d Versuchen aufgegeben [measurement=%s].",
                   core_constants.MAX_RETRIES, table_name)
    return False


_TAG_FIELD_SUFFIXES = ("_id", "_name", "_status")
_TAG_FIELD_KEYS = {"device_id", "actuator", "sensor_name", "state", "severity",
                   "trigger_reason", "alert_level", "ui_status", "error_code",
                   "display_type", "toast_color", "topic", "event_type"}


def _build_point(measurement: str, payload: dict, extra_tags: dict) -> Point:
    """Konvertiert ein JSON-Dict in einen InfluxDB-Point.

    Trennung Tags vs Fields ist eine InfluxDB-Performance-Best-Practice:
    Tags sind indiziert (geeignet fuer GROUP BY und Filter), Fields nicht.
    """
    point = Point(measurement)

    timestamp = payload.get("timestamp")
    if isinstance(timestamp, (int, float)):
        # Sekunden in UTC erwartet (siehe Datenflussarch. 4.x)
        point = point.time(datetime.fromtimestamp(float(timestamp), tz=timezone.utc),
                            WritePrecision.NS)

    for key, value in payload.items():
        if key == "timestamp":
            continue
        if key in extra_tags:
            continue

        is_tag = (key in _TAG_FIELD_KEYS
                  or any(key.endswith(suf) for suf in _TAG_FIELD_SUFFIXES))

        if isinstance(value, bool):
            # Booleans als Field (Tags muessen Strings sein)
            point = point.field(key, value)
        elif isinstance(value, (int, float)) and not is_tag:
            point = point.field(key, value)
        elif isinstance(value, str):
            if is_tag:
                point = point.tag(key, value)
            else:
                point = point.field(key, value)
        elif isinstance(value, dict):
            # Nested "details" wird als JSON-String gespeichert.
            import json
            point = point.field(key, json.dumps(value, ensure_ascii=False))
        elif value is None:
            continue
        else:
            point = point.field(key, str(value))

    for tag_key, tag_value in extra_tags.items():
        point = point.tag(tag_key, str(tag_value))

    return point


# ============================================================================
# 2. UPDATE (Coding Guidelines erweiterte Liste)
# ============================================================================

def db_update_record(table_name: str,
                     record_id: str,
                     update_data: dict) -> bool:
    """"Aktualisiert" einen Aktor-Status-Datensatz auf timeout.

    WICHTIG: InfluxDB ist eine TIME-SERIES-Datenbank und kennt kein
    klassisches UPDATE wie SQL. Die Datenflussarchitektur 3.5.2
    (check_active_timeouts) fordert dennoch das "Setzen" eines Datensatzes
    auf "timeout".

    Wir loesen das idiomatisch fuer InfluxDB: Ein neuer Point mit denselben
    Tag-Werten (insbesondere action_id) und state="timeout" wird mit einem
    Timestamp leicht NACH dem urspruenglichen running-Eintrag geschrieben.
    Damit ist beim Group-by-action_id der letzte State der timeout-Status.

    Args:
        table_name: Measurement, in dem der Datensatz lebt.
        record_id: action_id des Datensatzes.
        update_data: Felder, die fuer den neuen Datenpunkt gelten sollen
            (z. B. {"state": "timeout", "error_details": "..."}).

    Returns:
        bool: True, wenn der Folge-Datenpunkt geschrieben wurde.
    """
    update_copy = dict(update_data)
    update_copy["action_id"] = record_id
    update_copy["timestamp"] = update_copy.get("timestamp", int(time.time()))
    return db_insert_record(table_name, update_copy)


# ============================================================================
# 3. QUERY: Letzte N Datensaetze (Coding Guidelines core_database.py)
# ============================================================================

def db_get_latest_sensors(sensor_type: str, limit: int = 10) -> list[dict]:
    """Holt die letzten N Sensorwerte eines bestimmten Typs.

    Args:
        sensor_type: Einer aus SENSORS_REACTOR + SENSORS_ROOM
            (z. B. "ph", "co2").
        limit: Anzahl der gewuenschten Datensaetze.

    Returns:
        list[dict]: Liste von Dicts mit Keys "timestamp" und "value",
        absteigend nach Zeit sortiert. Leere Liste bei Fehler.
    """
    if sensor_type in core_constants.SENSORS_REACTOR:
        measurement = core_constants.MEASUREMENT_REACTOR_SENSORS
    elif sensor_type in core_constants.SENSORS_ROOM:
        measurement = core_constants.MEASUREMENT_ROOM_SENSORS
    else:
        _logger.error("Unbekannter sensor_type: %s", sensor_type)
        return []

    bucket = _resolve_bucket(measurement)
    flux = f'''
    from(bucket: "{bucket}")
      |> range(start: -1h)
      |> filter(fn: (r) => r["_measurement"] == "{measurement}")
      |> filter(fn: (r) => r["_field"] == "{sensor_type}")
      |> sort(columns: ["_time"], desc: true)
      |> limit(n: {int(limit)})
    '''
    return _execute_flux_to_records(flux)


# ============================================================================
# 4. QUERY: Zeitraum-basierte Datensaetze (erweiterte Liste)
# ============================================================================

def db_get_records_by_timeframe(table_name: str,
                                start_timestamp: int,
                                end_timestamp: int,
                                field_name: Optional[str] = None) -> list[dict]:
    """Holt alle Datensaetze eines Measurements in einem exakten Zeitfenster.

    Wird vor allem fuer die Algenwachstums-Berechnung benoetigt, die zwei
    diskrete 300s-Fenster vergleichen muss (Datenflussarch. 3.2 / 4.2.1.B).

    Args:
        table_name: Measurement-Name.
        start_timestamp: UNIX-Sekunden, inklusiv.
        end_timestamp: UNIX-Sekunden, exklusiv.
        field_name: Optionaler Filter auf ein einzelnes Field.

    Returns:
        list[dict]: Datensaetze, aufsteigend nach Zeit sortiert.
    """
    bucket = _resolve_bucket(table_name)
    start_iso = datetime.fromtimestamp(start_timestamp, tz=timezone.utc).isoformat()
    end_iso = datetime.fromtimestamp(end_timestamp, tz=timezone.utc).isoformat()

    filter_field = ""
    if field_name:
        filter_field = f'|> filter(fn: (r) => r["_field"] == "{field_name}")'

    flux = f'''
    from(bucket: "{bucket}")
      |> range(start: time(v: "{start_iso}"), stop: time(v: "{end_iso}"))
      |> filter(fn: (r) => r["_measurement"] == "{table_name}")
      {filter_field}
      |> sort(columns: ["_time"], desc: false)
    '''
    return _execute_flux_to_records(flux)


# ============================================================================
# 5. QUERY: Datensatz mit Bedingung (erweiterte Liste)
# ============================================================================

def db_get_latest_record_by_condition(table_name: str,
                                      condition_dict: dict) -> dict:
    """Holt den neuesten Datensatz, der allen Tag-Bedingungen entspricht.

    Wird z. B. fuer unquittierte Alarme verwendet:
        db_get_latest_record_by_condition(
            MEASUREMENT_ALARMS,
            {"ui_status": "unresolved", "actuator": "pump"},
        )

    Args:
        table_name: Measurement-Name.
        condition_dict: Tag-Filter (alle Bedingungen mit AND verknuepft).

    Returns:
        dict: Neuester Datensatz. Leeres dict, falls nichts gefunden.
    """
    bucket = _resolve_bucket(table_name)
    filter_lines = []
    for tag_key, tag_value in condition_dict.items():
        filter_lines.append(
            f'|> filter(fn: (r) => r["{tag_key}"] == "{tag_value}")'
        )
    filters_block = "\n      ".join(filter_lines)

    flux = f'''
    from(bucket: "{bucket}")
      |> range(start: -7d)
      |> filter(fn: (r) => r["_measurement"] == "{table_name}")
      {filters_block}
      |> sort(columns: ["_time"], desc: true)
      |> limit(n: 1)
    '''
    records = _execute_flux_to_records(flux)
    return records[0] if records else {}


# ============================================================================
# INTERN: Flux-Ausfuehrung
# ============================================================================

def _execute_flux_to_records(flux_query: str) -> list[dict]:
    """Fuehrt eine Flux-Query aus und konvertiert das Ergebnis in dicts.

    Wirft KEINE Exception - im Fehlerfall wird eine leere Liste zurueckgegeben
    und ein ERROR geloggt (Coding Guidelines Kapitel 5).
    """
    try:
        _get_client()
    except RuntimeError as exc:
        _logger.error("Flux-Query: %s", exc)
        return []

    try:
        tables = _query_api.query(flux_query)
    except (InfluxDBError, OSError) as exc:
        _logger.error("Flux-Query fehlgeschlagen: %s", exc)
        return []

    records: list[dict] = []
    for table in tables:
        for record in table.records:
            records.append({
                "timestamp": int(record.get_time().timestamp()),
                "field":     record.get_field(),
                "value":     record.get_value(),
                "measurement": record.get_measurement(),
                **{k: v for k, v in record.values.items()
                   if not k.startswith("_") and k not in ("result", "table")},
            })
    return records
