"""
core_utils.py - Algen-IoT
=========================

Zentrale Hilfsfunktionen zur JSON-Strukturierung, UUID- und
Timestamp-Erzeugung. Stellt sicher, dass alle Skripte identisch
formatierte Metadaten (analysis_id, action_id, alarm_id, timestamp)
erzeugen.

Bezieht sich auf:
- Coding Guidelines, Kapitel 3 (core_utils.py)
- Datenflussarchitektur und Datenstrukturen, Kapitel 4 (alle JSON-Schemata)

Autor: Algen-IoT Team
Datum: 2026-05-31
"""

import time
import uuid
from typing import Any, Optional

from algen_iot_core import core_constants
from algen_iot_core import core_logger


_logger = core_logger.get_logger("core_utils")


def get_current_timestamp() -> int:
    """Liefert den aktuellen UTC-UNIX-Timestamp in Sekunden.

    Systemweit identisch formatiert, damit alle JSON-Objekte denselben
    Zeitbezug haben. Verwendet bewusst Sekunden (nicht Millisekunden),
    weil saemtliche JSON-Beispiele in Kapitel 4 der Datenflussarchitektur
    Sekunden zeigen (z. B. 1734326400).

    Returns:
        int: UTC-UNIX-Timestamp in ganzen Sekunden.
    """
    return int(time.time())


def calculate_time_delta(timestamp_old: int, timestamp_new: int) -> int:
    """Berechnet die Zeitdifferenz zweier UNIX-Timestamps in Sekunden.

    Args:
        timestamp_old: Aelterer Zeitpunkt (UNIX-Sekunden).
        timestamp_new: Neuerer Zeitpunkt (UNIX-Sekunden).

    Returns:
        int: timestamp_new - timestamp_old (kann negativ sein, falls
        die Reihenfolge vertauscht uebergeben wurde).
    """
    return int(timestamp_new) - int(timestamp_old)


def generate_uuid(id_prefix: str) -> str:
    """Erzeugt eine eindeutige ID mit dem uebergebenen Praefix.

    Beispiel:
        generate_uuid("act-uuid-")  -> "act-uuid-7f5e2c9a-..."

    Args:
        id_prefix: Z. B. "act-uuid-", "air-analysis-", "alrm-uuid-".

    Returns:
        str: Praefix + UUID4.
    """
    return f"{id_prefix}{uuid.uuid4()}"


def build_standard_json(id_prefix: str,
                        parameters_dict: dict,
                        id_field_name: str = "id") -> dict:
    """Factory fuer standardisierte JSON-Objekte.

    Mergt die Pflichtfelder (UUID + Timestamp) mit den uebergebenen
    Nutzerwerten. Vorhandene Werte fuer id und timestamp in
    parameters_dict werden BEIBEHALTEN, damit Skripte gezielt eine
    bereits vorhandene ID weiterverwenden koennen.

    Args:
        id_prefix: Praefix fuer die UUID (siehe core_constants.UUID_PREFIX_*).
        parameters_dict: Nutzerspezifische Felder.
        id_field_name: Name des ID-Felds im resultierenden JSON
            (z. B. "action_id", "analysis_id", "alarm_id").

    Returns:
        dict: Standardisiertes JSON mit Pflichtmetadaten.

    Raises:
        TypeError: Wenn parameters_dict kein dict ist.
    """
    if not isinstance(parameters_dict, dict):
        raise TypeError("parameters_dict muss ein dict sein.")

    metadata = {
        id_field_name: generate_uuid(id_prefix),
        "timestamp":   get_current_timestamp(),
    }

    # Reihenfolge: zuerst Metadata, dann Nutzerwerte -- Nutzerwerte
    # ueberschreiben Metadata gezielt (z. B. wenn ein action_id schon
    # existiert und nur uebernommen werden soll).
    merged = {**metadata, **parameters_dict}
    return merged


def validate_enum_value(value: Any,
                        valid_values: set,
                        field_name: str) -> bool:
    """Prueft, ob ein Wert im erlaubten Enum-Set ist.

    Verhindert, dass Skripte freie Klartexte statt definierter Enums
    in JSON-Objekte schreiben (haeufiger Bug in den vorhandenen Skripten,
    z. B. action_recommendation als deutscher Freitext).

    Args:
        value: Zu pruefender Wert.
        valid_values: Set der erlaubten Werte (z. B.
            core_constants.DATA_STATUS_VALID_VALUES).
        field_name: Name des Feldes, zur klaren Fehlermeldung.

    Returns:
        bool: True, falls Wert gueltig.
    """
    if value not in valid_values:
        _logger.error(
            "Ungueltiger Wert '%s' fuer Feld '%s'. Erlaubt: %s",
            value, field_name, sorted(valid_values),
        )
        return False
    return True


def clamp(value: float, min_value: float, max_value: float) -> float:
    """Begrenzt einen Wert auf das Intervall [min_value, max_value].

    Wird z. B. fuer LED-Intensitaet (0-100) und target_lux (5000-7500)
    verwendet, um JSON-Befehle vor Versand zu validieren.

    Args:
        value: Eingangswert.
        min_value: Untere Grenze.
        max_value: Obere Grenze.

    Returns:
        float: Begrenzter Wert.
    """
    return max(min_value, min(max_value, value))


def safe_get_nested(data: dict, *keys, default: Optional[Any] = None) -> Any:
    """Robuster Zugriff auf verschachtelte Dict-Felder.

    Beispiel:
        safe_get_nested(payload, "details", "avg_co2", default=0.0)

    Args:
        data: Das Ausgangs-Dict.
        *keys: Beliebig viele Pfad-Komponenten.
        default: Rueckgabewert, wenn ein Pfad-Element fehlt.

    Returns:
        Any: Der gefundene Wert oder default.
    """
    current = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current
