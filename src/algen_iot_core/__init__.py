"""
Algen-IoT Core Library
======================

Zentrale Bibliothek für alle Skripte des Photobioreaktor-Systems (PBR).

Diese Bibliothek implementiert das DRY-Prinzip aus den Coding Guidelines (Kapitel 3)
und stellt allen capture_/analyze_/control_/bridge_/notify_-Skripten standardisierte
Funktionen für Hardware, Datenbank, MQTT, JSON-Strukturierung und Mathematik bereit.

Bezieht sich auf:
- Coding Guidelines, Kapitel 3 (Auslagerung allgemeiner Funktionen)
- Datenflussarchitektur und Datenstrukturen, Kapitel 3 und 4

Autor: Algen-IoT Team
Datum: 2026-05-31
Version: 1.0.0
"""

__all__ = [
    "core_constants",
    "core_database",
    "core_hardware",
    "core_logger",
    "core_math",
    "core_mqtt",
    "core_utils",
]

__version__ = "1.0.0"

# Hinweis: Module werden bewusst NICHT eager importiert, damit Skripte,
# die nur einen Teil der Bibliothek brauchen (z. B. nur core_math fuer
# einen Unit-Test), nicht zwingend paho-mqtt und influxdb-client
# installiert haben muessen. Stattdessen importiert jedes Skript gezielt:
#
#     from algen_iot_core import core_constants, core_database, core_mqtt
#
