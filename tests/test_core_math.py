"""
test_core_math.py - Unit-Tests fuer core_math

Verifiziert, dass die mathematischen Formeln EXAKT die Spezifikation aus
Datenflussarchitektur 4.2.1.A/B umsetzen.

Ausfuehren mit:
    pytest tests/test_core_math.py -v
"""

import pytest

from algen_iot_core import core_constants, core_math


# =============================================================================
# calculate_average
# =============================================================================

class TestCalculateAverage:
    def test_basic_average(self):
        assert core_math.calculate_average([1, 2, 3, 4, 5]) == 3.0

    def test_filters_sensor_error_value(self):
        """Der Fehlerwert -1.0 darf den Durchschnitt nicht verfaelschen."""
        result = core_math.calculate_average([10, 20, 30, -1.0, 40])
        assert result == 25.0

    def test_filters_none(self):
        result = core_math.calculate_average([10, None, 20, None])
        assert result == 15.0

    def test_empty_list_returns_none(self):
        assert core_math.calculate_average([]) is None

    def test_only_error_values_returns_none(self):
        assert core_math.calculate_average([-1.0, -1.0]) is None


# =============================================================================
# calculate_penalty_points - EXAKTE Formel aus Datenflussarch. 4.2.1.A Stufe 3
# =============================================================================

class TestCalculatePenaltyPoints:
    def test_formula_exact(self):
        """P = |X/M - 1| * S * 100. Beispiel aus Doku: X=850, M=700, S=1."""
        result = core_math.calculate_penalty_points(850, 700, 1)
        expected = abs(850 / 700 - 1) * 1 * 100
        assert result == pytest.approx(expected)
        assert result == pytest.approx(21.4285, rel=1e-3)

    def test_status_factor_zero_gives_zero_penalty(self):
        """Bei normal oder sensor_error ist S=0 -> P=0."""
        assert core_math.calculate_penalty_points(850, 700, 0) == 0.0

    def test_status_factor_doubles_penalty(self):
        p1 = core_math.calculate_penalty_points(850, 700, 1)
        p2 = core_math.calculate_penalty_points(850, 700, 2)
        assert p2 == pytest.approx(2 * p1)

    def test_avg_none_returns_zero(self):
        assert core_math.calculate_penalty_points(None, 700, 2) == 0.0

    def test_ideal_zero_raises(self):
        with pytest.raises(ValueError):
            core_math.calculate_penalty_points(100, 0, 1)


# =============================================================================
# get_status_factor - Datenflussarch. 4.2.1.A Stufe 2
# =============================================================================

class TestGetStatusFactor:
    def test_normal_is_zero(self):
        assert core_math.get_status_factor("normal") == 0

    def test_sensor_error_is_zero(self):
        """Spec-Sonderfall: sensor_error -> S=0 (Strafe nur durch check_sensors)."""
        assert core_math.get_status_factor("sensor_error") == 0

    def test_warning_is_one(self):
        assert core_math.get_status_factor("warning") == 1

    def test_error_is_two(self):
        assert core_math.get_status_factor("error") == 2

    def test_unknown_defaults_to_zero(self):
        assert core_math.get_status_factor("foobar") == 0


# =============================================================================
# calculate_quality_index - Stufe 4
# =============================================================================

class TestCalculateQualityIndex:
    def test_basic_average(self):
        """I = 100 - mean(penalties)"""
        result = core_math.calculate_quality_index([10, 20, 30, 40])
        assert result == 75.0

    def test_no_penalties_full_score(self):
        result = core_math.calculate_quality_index([0, 0, 0, 0])
        assert result == 100.0

    def test_clamped_to_zero(self):
        """Extreme Strafpunkte werden auf [0,100] begrenzt."""
        result = core_math.calculate_quality_index([1000, 1000, 1000, 1000])
        assert result == 0.0


# =============================================================================
# map_index_to_quality_label - Stufe 5
# =============================================================================

class TestMapIndexToLabel:
    """Bereiche: excellent 100-91, good 90-71, fair 70-41, poor 40-11, critical 10-0."""

    @pytest.mark.parametrize("index, expected", [
        (100, "excellent"),
        (95,  "excellent"),
        (91,  "excellent"),
        (90,  "good"),
        (80,  "good"),
        (71,  "good"),
        (70,  "fair"),
        (55,  "fair"),
        (41,  "fair"),
        (40,  "poor"),
        (25,  "poor"),
        (11,  "poor"),
        (10,  "critical"),
        (5,   "critical"),
        (0,   "critical"),
    ])
    def test_index_to_label(self, index, expected):
        assert core_math.map_index_to_quality_label(index) == expected


# =============================================================================
# map_quality_to_recommendation - Stufe 6 inkl. Sonderregeln
# =============================================================================

class TestRecommendationMapping:

    def test_standard_mappings(self):
        assert core_math.map_quality_to_recommendation("excellent") == "clean_air_less"
        assert core_math.map_quality_to_recommendation("good") == "keep_air_condition_same"
        assert core_math.map_quality_to_recommendation("fair") == "clean_air_more"
        assert core_math.map_quality_to_recommendation("poor") == "clean_air_more"
        assert core_math.map_quality_to_recommendation("critical") == "clean_air_more"

    def test_sensor_error_overrides(self):
        """Bei sensor_error wird IMMER check_sensors empfohlen."""
        result = core_math.map_quality_to_recommendation(
            "excellent", has_sensor_error=True, avg_co2=700
        )
        assert result == "check_sensors"

    def test_co2_low_special_rule(self):
        """CO2 < 300 -> clean_air_less, weil Algen noch viel absorbieren."""
        result = core_math.map_quality_to_recommendation(
            "poor", has_sensor_error=False, avg_co2=250
        )
        assert result == "clean_air_less"

    def test_turbidity_high_special_rule(self):
        """Truebung > 6.0 -> clean_air_less."""
        result = core_math.map_quality_to_recommendation(
            "poor", avg_co2=700, avg_turbidity=6.5
        )
        assert result == "clean_air_less"


# =============================================================================
# calculate_growth_rate + map_growth_rate_to_status - 4.2.1.B Stufe 5
# =============================================================================

class TestGrowthRate:
    def test_positive_growth(self):
        # T = (3.1 - 3.0) / 3.0 * 100 = 3.33%
        result = core_math.calculate_growth_rate(3.0, 3.1)
        assert result == pytest.approx(3.333, rel=1e-2)

    def test_negative_growth(self):
        result = core_math.calculate_growth_rate(3.0, 2.7)
        assert result == pytest.approx(-10.0)

    def test_zero_old_returns_none(self):
        assert core_math.calculate_growth_rate(0, 3.0) is None

    def test_none_inputs_return_none(self):
        assert core_math.calculate_growth_rate(None, 3.0) is None

    @pytest.mark.parametrize("rate, expected", [
        (5.0,   "growth"),
        (2.1,   "growth"),
        (2.0,   "stability"),
        (0.0,   "stability"),
        (-2.0,  "stability"),
        (-2.1,  "extinction"),
        (-9.0,  "extinction"),
        (-10.1, "contamination_suspected"),
        (-50.0, "contamination_suspected"),
    ])
    def test_rate_to_status(self, rate, expected):
        assert core_math.map_growth_rate_to_status(rate) == expected


# =============================================================================
# End-to-End: Vollstaendige Air-Quality-Pipeline
# =============================================================================

class TestEvaluateFullAirQuality:
    def test_perfect_conditions(self):
        result = core_math.evaluate_full_air_quality(
            aggregated_data={
                "avg_co2": 700, "avg_voc": 100,
                "avg_air_temp": 22, "avg_humidity": 50,
            },
            status_data={
                "co2_status": "normal", "voc_status": "normal",
                "air_temp_status": "normal", "humidity_status": "normal",
            },
        )
        assert result["air_quality_index"] == "excellent"
        assert result["action_recommendation"] == "clean_air_less"

    def test_sensor_error_triggers_check_sensors(self):
        result = core_math.evaluate_full_air_quality(
            aggregated_data={
                "avg_co2": 700, "avg_voc": 100,
                "avg_air_temp": 22, "avg_humidity": 50,
            },
            status_data={
                "co2_status": "sensor_error", "voc_status": "normal",
                "air_temp_status": "normal", "humidity_status": "normal",
            },
        )
        assert result["action_recommendation"] == "check_sensors"

    def test_extreme_errors_give_critical(self):
        result = core_math.evaluate_full_air_quality(
            aggregated_data={
                "avg_co2": 5000, "avg_voc": 900,
                "avg_air_temp": 40, "avg_humidity": 95,
            },
            status_data={
                "co2_status": "error", "voc_status": "error",
                "air_temp_status": "error", "humidity_status": "error",
            },
        )
        assert result["air_quality_index"] == "critical"
