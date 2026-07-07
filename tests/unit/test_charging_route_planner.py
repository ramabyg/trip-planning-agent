"""Deterministic charging planner: plan_charging_route against a fake road network.

The fake world (tests/conftest.py) places locations and Superchargers at mile
markers along a straight line, so expected SOC math is exact.
"""
import pytest

import tools
from schemas import ChargingPlan


def assert_plan_invariants(plan: dict):
    """Every successful plan must satisfy the schema and the safety rules."""
    validated = ChargingPlan(**plan)
    for segment in validated.segments:
        assert segment.arrival_soc >= tools.DEFAULT_SAFETY_BUFFER_SOC
    assert validated.total_distance_miles == pytest.approx(
        sum(s.distance_miles for s in validated.segments), abs=0.2)
    assert validated.total_duration_minutes == pytest.approx(
        sum(s.duration_minutes for s in validated.segments), abs=0.2)


def test_directly_reachable_single_segment(fake_maps):
    fake_maps.add_location("Home", 0)
    fake_maps.add_location("Nearby Town", 100)

    plan = tools.plan_charging_route("Home", "Nearby Town", 80, 280.0)

    assert_plan_invariants(plan)
    assert plan["directly_reachable"] is True
    assert len(plan["segments"]) == 1
    seg = plan["segments"][0]
    assert seg["action"] == "Arrive at destination"
    assert seg["departure_soc"] == 80
    assert seg["arrival_soc"] == 43  # 80 - 100 * 0.28 / 75 * 100 = 42.7
    assert seg["distance_miles"] == pytest.approx(100, abs=0.5)


def test_one_charging_stop(fake_maps):
    fake_maps.add_location("Home", 0)
    fake_maps.add_location("Far City", 300)
    fake_maps.add_charger("Midpoint Supercharger", 190)

    plan = tools.plan_charging_route("Home", "Far City", 90, 280.0)

    assert_plan_invariants(plan)
    assert plan["directly_reachable"] is False
    assert len(plan["segments"]) == 2

    leg1, leg2 = plan["segments"]
    assert "Midpoint Supercharger" in leg1["end"]
    assert leg1["action"] == f"Charge to {tools.CHARGE_TARGET_SOC}%"
    assert leg1["arrival_soc"] == 19  # 90 - 190 * 0.28/75*100 = 19.07
    assert leg2["departure_soc"] == tools.CHARGE_TARGET_SOC
    assert leg2["action"] == "Arrive at destination"


def test_multi_stop_route(fake_maps):
    fake_maps.add_location("Home", 0)
    fake_maps.add_location("Distant Park", 500)
    fake_maps.add_charger("First Supercharger", 190)
    fake_maps.add_charger("Second Supercharger", 350)

    plan = tools.plan_charging_route("Home", "Distant Park", 90, 280.0)

    assert_plan_invariants(plan)
    assert len(plan["segments"]) == 3
    assert "First Supercharger" in plan["segments"][0]["end"]
    assert "Second Supercharger" in plan["segments"][1]["end"]
    assert plan["segments"][2]["action"] == "Arrive at destination"
    assert plan["total_distance_miles"] == pytest.approx(500, abs=1.0)


def test_prefers_lowest_detour_charger(fake_maps):
    fake_maps.add_location("Home", 0)
    fake_maps.add_location("Far City", 300)
    # Both chargers are findable near the max-range point; the off-route one
    # (0.25 deg of longitude ~ 17 miles off the line) must lose.
    fake_maps.add_charger("Off-Route Supercharger", 195, lng=0.25)
    fake_maps.add_charger("On-Route Supercharger", 188)

    plan = tools.plan_charging_route("Home", "Far City", 90, 280.0)

    assert_plan_invariants(plan)
    assert "On-Route Supercharger" in plan["segments"][0]["end"]


def test_mountain_consumption_forces_stop(fake_maps):
    # 200 miles is fine at 280 Wh/mi from 90% (arrival 15.3%) but not at
    # 320 Wh/mi (arrival 4.7%) -> the mountain rate must add a stop.
    fake_maps.add_location("Home", 0)
    fake_maps.add_location("Mountain Lodge", 200)
    fake_maps.add_charger("Foothill Supercharger", 160)

    highway_plan = tools.plan_charging_route("Home", "Mountain Lodge", 90, 280.0)
    mountain_plan = tools.plan_charging_route("Home", "Mountain Lodge", 90, 320.0)

    assert highway_plan["directly_reachable"] is True
    assert mountain_plan["directly_reachable"] is False
    assert len(mountain_plan["segments"]) == 2


def test_no_charger_in_range_returns_error(fake_maps):
    fake_maps.add_location("Home", 0)
    fake_maps.add_location("Far City", 300)
    # No chargers registered at all.

    plan = tools.plan_charging_route("Home", "Far City", 90, 280.0)

    assert "error" in plan
    assert "Supercharger" in plan["error"]


def test_recursion_cap_prevents_infinite_planning(fake_maps):
    # Extreme consumption (1000 Wh/mi -> ~50 mile hops) and a 1000-mile trip:
    # the destination cannot be reached within MAX_CHARGING_STOPS.
    fake_maps.add_location("Home", 0)
    fake_maps.add_location("Far Far Away", 1000)
    for marker in range(50, 1000, 50):
        fake_maps.add_charger(f"Supercharger {marker}", marker)

    plan = tools.plan_charging_route("Home", "Far Far Away", 90, 1000.0)

    assert "error" in plan
    assert str(tools.MAX_CHARGING_STOPS) in plan["error"]


def test_route_error_propagates(fake_maps, monkeypatch):
    import maps_client

    def failing_route(origin, destination):
        return {"error": "No route found"}

    monkeypatch.setattr(maps_client, "compute_route", failing_route)
    plan = tools.plan_charging_route("Home", "Nowhere", 90, 280.0)
    assert plan == {"error": "No route found"}
