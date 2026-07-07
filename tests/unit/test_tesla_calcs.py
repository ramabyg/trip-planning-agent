"""Tesla range math: calculate_tesla_segments."""
import pytest

import tools


def test_known_values_100_miles_at_80_percent():
    result = tools.calculate_tesla_segments(100.0, 80)
    assert result["energy_needed_kwh"] == pytest.approx(28.0)
    assert result["soc_needed_percent"] == pytest.approx(37.3, abs=0.05)
    assert result["projected_arrival_soc"] == pytest.approx(42.7, abs=0.05)
    assert result["reachable"] is True


def test_reachable_just_above_buffer():
    # 240 miles at 100%: arrival ~10.4% >= 10% buffer
    result = tools.calculate_tesla_segments(240.0, 100)
    assert result["reachable"] is True
    assert result["projected_arrival_soc"] == pytest.approx(10.4, abs=0.05)


def test_unreachable_just_below_buffer():
    # 242 miles at 100%: arrival ~9.65% < 10% buffer
    result = tools.calculate_tesla_segments(242.0, 100)
    assert result["reachable"] is False
    assert "charge" in result["recommendation"].lower()


def test_mountain_rate_reduces_range():
    highway = tools.calculate_tesla_segments(100.0, 90, consumption_rate_wh_per_mile=280.0)
    mountain = tools.calculate_tesla_segments(100.0, 90, consumption_rate_wh_per_mile=320.0)
    assert mountain["max_range_before_charge"] < highway["max_range_before_charge"]
    assert mountain["energy_needed_kwh"] > highway["energy_needed_kwh"]
    # 90% SOC, 10% buffer, 320 Wh/mi -> (80/100) * 75/0.32 = 187.5 miles
    assert mountain["max_range_before_charge"] == pytest.approx(187.5)


def test_custom_safety_buffer():
    default_buffer = tools.calculate_tesla_segments(200.0, 90)
    high_buffer = tools.calculate_tesla_segments(200.0, 90, safety_buffer_soc=25)
    assert default_buffer["reachable"] is True
    assert high_buffer["reachable"] is False
    assert high_buffer["max_range_before_charge"] < default_buffer["max_range_before_charge"]
