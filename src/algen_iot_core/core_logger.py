"""
core_logger.py - Algen-IoT
==========================

Zentrales Logging-Modul. Ersetzt jeden print()-Aufruf im produktiven Code
(siehe Coding Guidelines Kapitel 5: "print() ist im produktiven Code tabu").

Bietet zwei Modi:
  1. get_logger(name): Strukturierter Python-Logger (INFO/WARNING/ERROR)
  2. log_message(text): Leichtgewichtige Debug-Ausgabe, gesteuert ueber
     IS_DEBUG_MODE_ENABLED. Im Produktivbetrieb komplett stumm.

Bezieht sich auf:
- Coding Guidelines, Kapitel 5 (Fehlerbehandlung, Logging und Versionskontrolle)

Autor: Algen-IoT Team
Datum: 2026-05-31
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from typing import Optional

from core import core_constants


# Registry, um pro Logger-Name nur einmal die Handler zu registrieren
_configured_loggers: set[str] = set()


def get_logger(logger_name: str,
               log_file_path: Optional[str] = None,
               log_level: int = logging.INFO) -> logging.Logger:
    """Erzeugt oder liefert einen konfigurierten Logger zurueck.

    Schreibt parallel auf stdout und (falls log_file_path gesetzt) in eine
    rotierende Logdatei. Wird derselbe logger_name mehrfach angefordert, wird
    der bereits konfigurierte Logger wiederverwendet (verhindert doppelte
    Handler).

    Args:
        logger_name: Eindeutiger Name des Loggers (z.B. "capture_room_climate").
        log_file_path: Optionaler Pfad zur Logdatei. None = nur stdout.
        log_level: logging.INFO (Default), logging.DEBUG oder logging.WARNING.

    Returns:
        logging.Logger: Konfigurierter Logger.

    Raises:
        OSError: Wenn die Logdatei nicht angelegt werden kann.
    """
    logger = logging.getLogger(logger_name)

    if logger_name in _configured_loggers:
        return logger

    logger.setLevel(log_level)
    logger.propagate = False

    formatter = logging.Formatter(
        fmt=core_constants.LOG_FORMAT,
        datefmt=core_constants.LOG_DATE_FORMAT,
    )

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    if log_file_path:
        try:
            os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
            file_handler = RotatingFileHandler(
                filename=log_file_path,
                maxBytes=10 * 1024 * 1024,   # 10 MB
                backupCount=5,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except OSError as exc:
            # Bewusst nicht raisen: Logger soll immer benutzbar bleiben
            logger.warning("Logdatei konnte nicht angelegt werden (%s): %s",
                           log_file_path, exc)

    _configured_loggers.add(logger_name)
    return logger


def log_message(text: str, level: str = "INFO") -> None:
    """Leichtgewichtige Hilfsfunktion fuer Debug-Ausgaben.

    Verhalten gemaess Coding Guidelines Kapitel 5:
    - IS_DEBUG_MODE_ENABLED == True : Ausgabe auf stdout
    - IS_DEBUG_MODE_ENABLED == False: Komplett stumm (CPU-Zyklen sparen)

    Diese Funktion ist die einzige zulaessige Alternative zu print() im
    produktiven Code, da sie zentral abschaltbar ist.

    Args:
        text: Die Nachricht.
        level: "INFO" | "WARNING" | "ERROR" (nur fuer Praefix-Anzeige).

    Returns:
        None.
    """
    if not core_constants.IS_DEBUG_MODE_ENABLED:
        return
    print(f"[DEBUG-{level}] {text}", flush=True)
