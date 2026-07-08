"""Elevation-adaptive energy model and charging-curve math (pure, no network)."""
import pytest

import maps_client
import tools

MILES_PER_DEG_LAT = maps_client.haversine_miles((0.0, 0.0), (1.0, 0.0))


def line(miles: float, step_miles: float = 1.0) -> list:
    """(lat, lng) points along a north-south line, one per step_miles."""
    n = int(miles / step_miles)
    return [(i * step_miles / MILES_PER_DEG_LAT, 0.0) for i in range(n + 1)]


class TestBuildEnergyProfile:
    def test_flat_terrain_uses_base_rate(self):
        points = line(100)
        profile = tools.build_energy_profile(points, [0.0] * len(points))
        assert profile
        for chunk in profile:
            assert chunk["wh_per_mile"] == pytest.approx(tools.DEFAULT_CONSUMPTION_WH_PER_MILE)
        assert tools.profile_energy_kwh(profile) == pytest.approx(28.0, abs=0.1)

    def test_climb_raises_only_the_climbing_chunks(self):
        points = line(20)
        # Miles 0-10 climb 10 m/mile; miles 10-20 flat.
        elevations = [min(m, 10) * 10.0 for m in range(len(points))]
        profile = tools.build_energy_profile(points, elevations)
        climb_rate = profile[0]["wh_per_mile"]
        flat_rate = profile[-1]["wh_per_mile"]
        # 10 m/mile * 7 Wh/m = +70 Wh/mile on the climb only.
        assert climb_rate == pytest.approx(280 + 70, abs=1)
        assert flat_rate == pytest.approx(280, abs=1)

    def test_descent_credited_at_conservative_40_percent(self):
        assert tools.REGEN_RECOVERY == 0.40
        assert tools.WH_PER_METER_DESCENT_CREDIT == pytest.approx(2.8)
        points = line(10)
        # 10 m/mile descent: credit is 28 Wh/mile, NOT the ~42 a 60% recovery would give.
        elevations = [-m * 10.0 for m in range(len(points))]
        profile = tools.build_energy_profile(points, elevations)
        assert profile[0]["wh_per_mile"] == pytest.approx(280 - 28, abs=1)

    def test_extreme_grades_are_clamped(self):
        points = line(10)
        steep_up = [m * 100.0 for m in range(len(points))]     # 100 m/mile
        steep_down = [-m * 100.0 for m in range(len(points))]
        up_profile = tools.build_energy_profile(points, steep_up)
        down_profile = tools.build_energy_profile(points, steep_down)
        assert up_profile[0]["wh_per_mile"] == tools.MAX_CHUNK_WH_PER_MILE
        assert down_profile[0]["wh_per_mile"] == tools.MIN_CHUNK_WH_PER_MILE

    def test_flat_override_ignores_missing_elevations(self):
        points = line(50)
        profile = tools.build_energy_profile(points, None, 320.0)
        for chunk in profile:
            assert chunk["wh_per_mile"] == 320.0
        assert tools.profile_energy_kwh(profile) == pytest.approx(16.0, abs=0.1)


class TestPointAtEnergyBudget:
    def test_budget_maps_to_distance_on_flat_terrain(self):
        points = line(100)
        profile = tools.build_energy_profile(points, [0.0] * len(points))
        # 14 kWh at 280 Wh/mile = 50 miles.
        point = tools.point_at_energy_budget(profile, 14.0)
        assert point[0] * MILES_PER_DEG_LAT == pytest.approx(50, abs=1.5)

    def test_budget_beyond_route_returns_last_point(self):
        points = line(100)
        profile = tools.build_energy_profile(points, [0.0] * len(points))
        point = tools.point_at_energy_budget(profile, 1000.0)
        assert point == points[-1]

    def test_climb_shortens_reachable_distance(self):
        points = line(100)
        flat = tools.build_energy_profile(points, [0.0] * len(points))
        hilly = tools.build_energy_profile(points, [m * 20.0 for m in range(len(points))])
        flat_reach = tools.point_at_energy_budget(flat, 14.0)[0]
        hilly_reach = tools.point_at_energy_budget(hilly, 14.0)[0]
        assert hilly_reach < flat_reach

    def test_empty_profile_raises(self):
        with pytest.raises(ValueError):
            tools.point_at_energy_budget([], 10.0)


class TestChargeTime:
    def test_fast_band_at_250_kw(self):
        # 10->80%: 33.75 kWh @170kW + 18.75 kWh @95kW = ~23.8 min.
        minutes = tools.estimate_charge_time_minutes(10, 80, 250.0)
        assert minutes == pytest.approx(23.8, abs=0.2)

    def test_above_80_is_much_slower_per_kwh(self):
        below = tools.estimate_charge_time_minutes(10, 25, 250.0)   # 11.25 kWh
        above = tools.estimate_charge_time_minutes(80, 95, 250.0)   # 11.25 kWh
        assert above > below * 2.5

    def test_station_power_caps_the_rate(self):
        fast_station = tools.estimate_charge_time_minutes(10, 80, 250.0)
        slow_station = tools.estimate_charge_time_minutes(10, 80, 62.5)
        assert slow_station > fast_station * 1.8

    def test_no_charge_needed_is_zero(self):
        assert tools.estimate_charge_time_minutes(80, 80, 250.0) == 0.0
        assert tools.estimate_charge_time_minutes(85, 80, 250.0) == 0.0
