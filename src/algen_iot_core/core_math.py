"""
core_math.py - Algen-IoT
========================

Zentrale mathematische Hilfsfunktionen fuer alle Analyse-Skripte.
Implementiert die in der Datenflussarchitektur 4.2.1 spezifizierten
Formeln EXAKT, damit Luft- und Algenanalyse konsistente Ergebnisse
liefern.

WICHTIG: Die Strafformel und Score-Berechnung sind in der
Datenflussarchitektur verbindlich vorgegeben. Abweichungen davon
fuehren zu falschen Aktor-Empfehlungen (vgl. das vorhandene
analyze_air_quality.py-Skript, das gegen alle vier Formeln verstoesst).

Bezieht sich auf:
- Coding Guidelines, Kapitel 3 (core_math.py)
- Datenflussarchitektur und Datenstrukturen, Kapitel 4.2.1.A/B
  (Stufen 0-6, alle Penalty-, Score-, Wachstumsformeln)

Autor: Algen-IoT Team
Datum: 2026-05-31
"""

from typing import Iterable, Optional

from algen_iot_core import core_constants
from algen_iot_core import core_logger


_logger = core_logger.get_logger("core_math")


def calculate_average(value_list: Iterable[float]) -> Optional[float]:
    """Berechnet den arithmetischen Mittelwert einer Werteliste.

    Filtert automatisch den Sensor-Fehlerwert SENSOR_ERROR_RETURN_VALUE
    (= -1.0) und None heraus, damit Kommunikationsfehler den Durchschnitt
    nicht verfaelschen (siehe Coding Guidelines, Beschreibung
    calculate_average).

    Args:
        value_list: Iterable mit Sensorwerten.

    Returns:
        float: Mittelwert der gueltigen Werte.
        None : Falls keine gueltigen Werte vorhanden sind. Aufrufende
               Skripte muessen None auf data_status = sensor_error mappen
               (siehe Datenflussarch. 3.8 Absicherungsregel).
    """
    valid_values = [
        v for v in value_list
        if v is not None and v != core_constants.SENSOR_ERROR_RETURN_VALUE
    ]
    if not valid_values:
        return None
    return sum(valid_values) / len(valid_values)


def get_status_factor(data_status: str) -> int:
    """Liefert den S-Faktor fuer die Strafformel.

    Mapping gemaess Datenflussarch. 4.2.1.A Stufe 2:
        normal       -> 0
        sensor_error -> 0  (keine Strafe, aber check_sensors-Sonderregel!)
        warning      -> 1
        error        -> 2

    Args:
        data_status: Einer der Werte aus DATA_STATUS_VALID_VALUES.

    Returns:
        int: 0, 1 oder 2.
    """
    return core_constants.STATUS_FACTOR_MAP.get(data_status, 0)


def calculate_penalty_points(avg_value: Optional[float],
                              ideal_value: float,
                              status_factor: int) -> float:
    """Strafpunkte P fuer einen einzelnen Sensor.

    Formel aus Datenflussarch. 4.2.1.A Stufe 3:

        P = |X / M - 1| * S * 100

    Beispiel:
        avg_value=850, ideal_value=700, status_factor=1
        P = |850/700 - 1| * 1 * 100 = 21.43

    Args:
        avg_value: Mittelwert X der letzten 300 Sekunden. None -> P = 0.
        ideal_value: Idealwert M (goldene Mitte). Darf nicht 0 sein.
        status_factor: S aus get_status_factor() (0, 1 oder 2).

    Returns:
        float: Strafpunkte (>=0).

    Raises:
        ValueError: Wenn ideal_value == 0 (Division durch Null).
    """
    if avg_value is None:
        return 0.0
    if ideal_value == 0:
        raise ValueError("ideal_value darf nicht 0 sein (Division durch Null).")
    if status_factor == 0:
        return 0.0

    return abs(avg_value / ideal_value - 1.0) * status_factor * 100.0


def calculate_quality_index(penalty_points_list: Iterable[float]) -> float:
    """Berechnet den Quality Index I aus der Liste der Strafpunkte.

    Formel aus Datenflussarch. 4.2.1.A Stufe 4:

        I = 100 - (P1 + P2 + P3 + P4) / N

    Wird sowohl fuer den air_quality_index (Luft, 4 Parameter) als auch
    fuer den vitality_score (Algen, 4 Parameter) verwendet.

    Args:
        penalty_points_list: Liste von Strafpunkten (z. B.
            [P_co2, P_voc, P_temp, P_hum]).

    Returns:
        float: Quality Index im Bereich [0, 100].
    """
    penalty_list = list(penalty_points_list)
    if not penalty_list:
        return 100.0

    avg_penalty = sum(penalty_list) / len(penalty_list)
    index = 100.0 - avg_penalty
    # Begrenzung auf [0, 100] - extreme Abweichungen koennten sonst
    # negative Werte erzeugen.
    return max(0.0, min(100.0, index))


def map_index_to_quality_label(quality_index: float) -> str:
    """Bildet den Index auf das Quality-Label ab.

    Bereiche aus Datenflussarch. 4.2.1.A Stufe 5:
        100-91 -> excellent
         90-71 -> good
         70-41 -> fair
         40-11 -> poor
         10-0  -> critical

    Args:
        quality_index: I aus calculate_quality_index() (0-100).

    Returns:
        str: Einer der Werte aus AIR_QUALITY_INDEX_VALID_VALUES.
    """
    for lower_bound, label in core_constants.QS_RANGES:
        if quality_index >= lower_bound:
            return label
    return core_constants.AIR_QUALITY_INDEX_CRITICAL


def map_quality_to_recommendation(quality_label: str,
                                   has_sensor_error: bool = False,
                                   avg_co2: Optional[float] = None,
                                   avg_turbidity: Optional[float] = None
                                   ) -> str:
    """Bildet das Quality-Label auf eine action_recommendation ab.

    Implementiert die Prio-Tabelle Datenflussarch. 4.2.1.A Stufe 6 inklusive
    der beiden Sonderregeln:
      1. Bei sensor_error -> check_sensors anhaengen (hier als alleiniger
         Rueckgabewert, weil nur ein String erlaubt ist).
      2. Bei CO2 < 300 ppm ODER Truebung > 6.0 g/l -> clean_air_less
         (Algen absorbieren noch sehr stark, also nicht mehr lueften).

    Args:
        quality_label: Aus map_index_to_quality_label().
        has_sensor_error: True, wenn mindestens ein Sensor sensor_error
            liefert.
        avg_co2: Durchschnitts-CO2 fuer Sonderregel. None = inaktiv.
        avg_turbidity: Durchschnitts-Truebung fuer Sonderregel. None =
            inaktiv.

    Returns:
        str: Einer der Werte aus ACTION_RECOMMENDATION_VALID_VALUES.
    """
    if has_sensor_error:
        return core_constants.ACTION_RECOMMENDATION_CHECK_SENSORS

    if avg_co2 is not None and avg_co2 < core_constants.CO2_SPECIAL_RULE_THRESHOLD:
        return core_constants.ACTION_RECOMMENDATION_CLEAN_LESS

    if (avg_turbidity is not None
            and avg_turbidity > core_constants.TURBIDITY_SPECIAL_RULE_THRESHOLD):
        return core_constants.ACTION_RECOMMENDATION_CLEAN_LESS

    return core_constants.QUALITY_TO_RECOMMENDATION_MAP.get(
        quality_label,
        core_constants.ACTION_RECOMMENDATION_NONE,
    )


def calculate_growth_rate(turbidity_old: Optional[float],
                          turbidity_new: Optional[float]) -> Optional[float]:
    """Wachstumsrate T in Prozent (Datenflussarch. 4.2.1.B Stufe 5).

    Formel:
        T = (T_new - T_old) / T_old * 100

    Args:
        turbidity_old: Durchschnitts-Truebung vorheriges 300s-Fenster.
        turbidity_new: Durchschnitts-Truebung aktuelles 300s-Fenster.

    Returns:
        float: Prozentuale Veraenderung. None, falls keine Berechnung
            moeglich ist (fehlende Werte oder turbidity_old == 0).
    """
    if turbidity_old is None or turbidity_new is None:
        return None
    if turbidity_old == 0:
        # Division durch 0 vermeiden -- bei Truebung == 0 ist die Kultur
        # ohnehin tot, daher null zurueckgeben.
        return None
    return (turbidity_new - turbidity_old) / turbidity_old * 100.0


def map_growth_rate_to_status(growth_rate: Optional[float]) -> str:
    """Bildet die Wachstumsrate auf einen growth_status ab.

    Schwellwerte aus Datenflussarch. 4.2.1.B Stufe 5:
        T < -10% -> contamination_suspected
        T < -2%  -> extinction
        -2% <= T <= 2% -> stability
        T > 2%   -> growth

    Args:
        growth_rate: T aus calculate_growth_rate() in Prozent.

    Returns:
        str: Einer der Werte aus GROWTH_STATUS_VALID_VALUES.
    """
    if growth_rate is None:
        return core_constants.GROWTH_STATUS_STABILITY

    if growth_rate < core_constants.GROWTH_RATE_THRESHOLD_CONTAMINATION_PCT:
        return core_constants.GROWTH_STATUS_CONTAMINATION

    if growth_rate < -core_constants.GROWTH_RATE_THRESHOLD_STABILITY_PCT:
        return core_constants.GROWTH_STATUS_EXTINCTION

    if growth_rate <= core_constants.GROWTH_RATE_THRESHOLD_STABILITY_PCT:
        return core_constants.GROWTH_STATUS_STABILITY

    return core_constants.GROWTH_STATUS_GROWTH


def evaluate_full_air_quality(aggregated_data: dict,
                              status_data: dict) -> dict:
    """High-Level-Funktion: Berechnet komplette Luftanalyse in einem Aufruf.

    Bequemlichkeits-Wrapper, der die Stufen 0-6 hintereinander ausfuehrt.
    Gibt die fertigen Felder fuer das Analyse-JSON (Datenflussarch. 4.2.1)
    zurueck.

    Args:
        aggregated_data: Dict mit Keys "avg_co2", "avg_voc", "avg_air_temp",
            "avg_humidity" (alle float oder None).
        status_data: Dict mit Keys "co2_status", "voc_status",
            "air_temp_status", "humidity_status" (alle aus
            DATA_STATUS_VALID_VALUES).

    Returns:
        dict: {
            "air_quality_index": str,
            "action_recommendation": str,
            "vitality_score_air": float (= air_quality_index numerisch),
        }
    """
    penalty_points = []
    has_sensor_error = False

    for sensor_name in core_constants.SENSORS_ROOM:
        avg_value = aggregated_data.get(f"avg_{sensor_name}")
        sensor_status = status_data.get(f"{sensor_name}_status",
                                         core_constants.DATA_STATUS_NORMAL)
        if sensor_status == core_constants.DATA_STATUS_SENSOR_ERROR:
            has_sensor_error = True

        status_factor = get_status_factor(sensor_status)
        ideal = core_constants.IDEAL_VALUES_MAP[sensor_name]
        penalty_points.append(
            calculate_penalty_points(avg_value, ideal, status_factor)
        )

    quality_index = calculate_quality_index(penalty_points)
    quality_label = map_index_to_quality_label(quality_index)
    recommendation = map_quality_to_recommendation(
        quality_label,
        has_sensor_error=has_sensor_error,
        avg_co2=aggregated_data.get("avg_co2"),
    )

    return {
        "air_quality_index":    quality_label,
        "action_recommendation": recommendation,
        "quality_index_numeric": round(quality_index, 2),
    }


def evaluate_full_algae_vitality(aggregated_data: dict,
                                  status_data: dict,
                                  turbidity_old: Optional[float] = None
                                  ) -> dict:
    """High-Level-Funktion: Berechnet komplette Algenanalyse.

    Args:
        aggregated_data: Dict mit "avg_water_temp", "avg_ph",
            "avg_turbidity", "avg_light_intensity".
        status_data: Dict mit "*_status" Feldern.
        turbidity_old: Truebungs-Mittelwert des vorherigen
            300s-Intervalls (fuer growth_status). None -> stability.

    Returns:
        dict: {
            "vitality_score": float,
            "growth_status":  str,
        }
    """
    penalty_points = []

    for sensor_name in core_constants.SENSORS_REACTOR:
        avg_value = aggregated_data.get(f"avg_{sensor_name}")
        sensor_status = status_data.get(f"{sensor_name}_status",
                                         core_constants.DATA_STATUS_NORMAL)
        status_factor = get_status_factor(sensor_status)
        ideal = core_constants.IDEAL_VALUES_MAP[sensor_name]
        penalty_points.append(
            calculate_penalty_points(avg_value, ideal, status_factor)
        )

    vitality_score = calculate_quality_index(penalty_points)
    growth_rate = calculate_growth_rate(
        turbidity_old,
        aggregated_data.get("avg_turbidity"),
    )
    growth_status = map_growth_rate_to_status(growth_rate)

    return {
        "vitality_score": round(vitality_score, 2),
        "growth_status":  growth_status,
    }
