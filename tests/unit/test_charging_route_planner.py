"""Deterministic charging planner: plan_charging_route against a fake road network.

The fake world (tests/conftest.py) places locations and chargers at mile
markers along a straight line with configurable terrain, so expected SOC math
is exact (flat terrain reproduces the 280 Wh/mile base rate).
"""
import pytest

import tools
from schemas import ChargingPlan


def assert_plan_invariants(plan: dict):
    """Every successful plan must satisfy the schema and the safety rules."""
    validated = ChargingPlan(**plan)
    for segment in validated.segments:
        assert segment.arrival_soc >= tools.DEFAULT_SAFETY_BUFFER_SOC
        # Departure SOC is a state (up to 100 at the origin or on a
        # pass-through stop); *charge targets* are capped separately below.
        assert segment.departure_soc <= 100
    assert validated.total_distance_miles == pytest.approx(
        sum(s.distance_miles for s in validated.segments), abs=0.2)
    assert validated.total_duration_minutes == pytest.approx(
        sum(s.duration_minutes for s in validated.segments), abs=0.2)
    # Every stop carries a sized action and a time estimate; a charge target
    # never exceeds the 95% cap; the arrival segment carries neither.
    for segment in validated.segments[:-1]:
        assert (segment.action.startswith("Charge to ")
                or segment.action.startswith("No charging needed"))
        assert segment.charge_time_minutes is not None and segment.charge_time_minutes >= 0
        if segment.action.startswith("Charge to "):
            target = int(segment.action.removeprefix("Charge to ").split("%")[0])
            assert target <= tools.MAX_CHARGE_TARGET_SOC
    assert validated.segments[-1].action == "Arrive at destination"
    assert validated.segments[-1].charge_time_minutes is None


def test_directly_reachable_single_segment(fake_maps):
    fake_maps.add_location("Home", 0)
    fake_maps.add_location("Nearby Town", 100)

    plan = tools.plan_charging_route("Home", "Nearby Town", 80)

    assert_plan_invariants(plan)
    assert plan["directly_reachable"] is True
    assert len(plan["segments"]) == 1
    seg = plan["segments"][0]
    assert seg["departure_soc"] == 80
    assert seg["arrival_soc"] == 43  # 80 - 100 * 0.28 / 75 * 100 = 42.7
    assert seg["distance_miles"] == pytest.approx(100, abs=0.5)
    assert seg["avg_consumption_wh_per_mile"] == pytest.approx(280, abs=1)
    assert plan["total_charge_time_minutes"] is None
    assert plan["notes"] is None


def test_one_charging_stop(fake_maps):
    fake_maps.add_location("Home", 0)
    fake_maps.add_location("Far City", 300)
    fake_maps.add_charger("Midpoint Charger", 190)

    plan = tools.plan_charging_route("Home", "Far City", 90)

    assert_plan_invariants(plan)
    assert plan["directly_reachable"] is False
    assert len(plan["segments"]) == 2

    leg1, leg2 = plan["segments"]
    assert "Midpoint Charger" in leg1["end"]
    # Next leg is 110 mi (41.1% + buffer + margin = 56.1%), so the default 80% target holds.
    assert leg1["action"].startswith("Charge to 80%")
    assert leg1["arrival_soc"] == 19  # 90 - 190 * 0.28/75*100 = 19.07
    assert leg1["charger_power_kw"] == 150.0
    assert leg1["charger_amenities"] == ["Fake Diner"]
    assert leg1["charge_time_minutes"] > 0
    assert leg2["departure_soc"] == tools.DEFAULT_CHARGE_TARGET_SOC
    assert plan["total_charge_time_minutes"] == pytest.approx(
        leg1["charge_time_minutes"], abs=0.1)


def test_multi_stop_route(fake_maps):
    fake_maps.add_location("Home", 0)
    fake_maps.add_location("Distant Park", 500)
    fake_maps.add_charger("First Charger", 190)
    fake_maps.add_charger("Second Charger", 350)

    plan = tools.plan_charging_route("Home", "Distant Park", 90)

    assert_plan_invariants(plan)
    assert len(plan["segments"]) == 3
    assert "First Charger" in plan["segments"][0]["end"]
    assert "Second Charger" in plan["segments"][1]["end"]
    assert plan["total_distance_miles"] == pytest.approx(500, abs=1.0)


def test_prefers_lowest_detour_charger(fake_maps):
    fake_maps.add_location("Home", 0)
    fake_maps.add_location("Far City", 300)
    # Both chargers are findable near the max-range point; the off-route one
    # (0.25 deg of longitude ~ 17 miles off the line) must lose.
    fake_maps.add_charger("Off-Route Charger", 195, lng=0.25)
    fake_maps.add_charger("On-Route Charger", 188)

    plan = tools.plan_charging_route("Home", "Far City", 90)

    assert_plan_invariants(plan)
    assert "On-Route Charger" in plan["segments"][0]["end"]


def test_hill_forces_stop_only_when_present(fake_maps):
    # 180 miles at 80% is fine on flat terrain (arrival 12.8%) but a mountain
    # pass mid-route burns ~4-5 extra SOC, dropping arrival below the buffer.
    fake_maps.add_location("Home", 0)
    fake_maps.add_location("Mountain Lodge", 180)
    fake_maps.add_charger("Foothill Charger", 140)

    flat_plan = tools.plan_charging_route("Home", "Mountain Lodge", 80)
    fake_maps.set_hill(80, 120, 1500)
    hill_plan = tools.plan_charging_route("Home", "Mountain Lodge", 80)

    assert flat_plan["directly_reachable"] is True
    assert hill_plan["directly_reachable"] is False
    assert len(hill_plan["segments"]) == 2
    # Consumption is granular: the climb leg averages above base rate, while
    # the flat final leg stays at the 280 base.
    assert hill_plan["segments"][0]["avg_consumption_wh_per_mile"] > 285
    assert hill_plan["segments"][1]["avg_consumption_wh_per_mile"] == pytest.approx(280, abs=1)


def test_charges_above_80_when_next_leg_demands_it(fake_maps):
    # Only charger is early in the route; the remaining 180-mile leg needs
    # 67.2% + 10 buffer + 5 margin = 82.2% -> target 83%, not the 80% default.
    fake_maps.add_location("Home", 0)
    fake_maps.add_location("Far City", 240)
    fake_maps.add_charger("Early Charger", 60)

    plan = tools.plan_charging_route("Home", "Far City", 90)

    assert_plan_invariants(plan)
    leg1, leg2 = plan["segments"]
    assert leg1["action"].startswith("Charge to 83%")
    assert leg2["departure_soc"] == 83
    assert leg2["arrival_soc"] >= tools.DEFAULT_SAFETY_BUFFER_SOC


def test_pass_through_stop_never_charges_above_95(fake_maps):
    # Leaving at 100%, the only charger reachable from the origin is 25 mi out
    # (arrival ~91%). The next hop needs only an 85% departure, so the stop is
    # a pass-through: no charging, keep the 91% state, and no action anywhere
    # may charge above the 95% cap.
    fake_maps.add_location("Home", 0)
    fake_maps.add_location("Far City", 420)
    fake_maps.add_charger("Near Charger", 25)
    # Off-route just enough (~20.7 mi) to be invisible from the origin's
    # search samples but findable from Near Charger's.
    fake_maps.add_charger("Mid Charger", 210, lng=0.3)

    plan = tools.plan_charging_route("Home", "Far City", 100)

    assert_plan_invariants(plan)
    seg1, seg2, seg3 = plan["segments"]
    assert "Near Charger" in seg1["end"]
    assert seg1["action"].startswith("No charging needed")
    assert seg1["charge_time_minutes"] == 0.0
    assert seg2["departure_soc"] == 91  # unchanged state, not a charge to 91
    assert "Mid Charger" in seg2["end"]
    assert seg2["action"].startswith("Charge to 94%")
    assert seg3["action"] == "Arrive at destination"


def test_current_soc_out_of_range_returns_error(fake_maps):
    fake_maps.add_location("Home", 0)
    fake_maps.add_location("Far City", 300)

    too_high = tools.plan_charging_route("Home", "Far City", 105)
    too_low = tools.plan_charging_route("Home", "Far City", 5)

    assert "current_soc" in too_high["error"]
    assert "current_soc" in too_low["error"]


def test_unreachable_even_at_95_returns_error(fake_maps):
    # From the only charger, 240 miles needs 89.6% while 95% - buffer allows
    # only 85% worth: no plan exists and the error must say so.
    fake_maps.add_location("Home", 0)
    fake_maps.add_location("Far City", 300)
    fake_maps.add_charger("Early Charger", 60)

    plan = tools.plan_charging_route("Home", "Far City", 90)

    assert "error" in plan
    assert "95" in plan["error"]


def test_skips_confirmed_dead_charger(fake_maps):
    fake_maps.add_location("Home", 0)
    fake_maps.add_location("Far City", 300)
    fake_maps.add_charger("Dead Charger", 190, available_count=0)
    fake_maps.add_charger("Live Charger", 188)

    plan = tools.plan_charging_route("Home", "Far City", 90)

    assert_plan_invariants(plan)
    assert "Live Charger" in plan["segments"][0]["end"]


def test_live_availability_outranks_unknown(fake_maps):
    # The unknown-status charger sits closer to the route sample point, but a
    # station with live availability data wins the ranking.
    fake_maps.add_location("Home", 0)
    fake_maps.add_location("Far City", 300)
    fake_maps.add_charger("Unknown Status Charger", 188, available_count=None)
    fake_maps.add_charger("Live Charger", 195, available_count=2)

    plan = tools.plan_charging_route("Home", "Far City", 90)

    assert_plan_invariants(plan)
    assert "Live Charger" in plan["segments"][0]["end"]


def test_amenity_charger_beats_isolated_one(fake_maps):
    fake_maps.add_location("Home", 0)
    fake_maps.add_location("Far City", 300)
    fake_maps.add_charger("Isolated Charger", 188, amenities=[])
    fake_maps.add_charger("Cozy Charger", 190, amenities=["Fake Cafe", "Fake Market"])

    plan = tools.plan_charging_route("Home", "Far City", 90)

    assert_plan_invariants(plan)
    assert "Cozy Charger" in plan["segments"][0]["end"]
    assert plan["segments"][0]["charger_amenities"] == ["Fake Cafe", "Fake Market"]


def test_slow_charger_fallback_adds_note(fake_maps):
    # No >=100 kW station exists; the planner falls back to a 62.5 kW one and
    # must warn about the slower stop.
    fake_maps.add_location("Home", 0)
    fake_maps.add_location("Far City", 300)
    fake_maps.add_charger("Slow Charger", 190, max_kw=62.5)

    plan = tools.plan_charging_route("Home", "Far City", 90)

    assert_plan_invariants(plan)
    assert "Slow Charger" in plan["segments"][0]["end"]
    assert plan["segments"][0]["charger_power_kw"] == 62.5
    assert plan["notes"] and any("62" in note for note in plan["notes"])


def test_no_charger_in_range_returns_error(fake_maps):
    fake_maps.add_location("Home", 0)
    fake_maps.add_location("Far City", 300)
    # No chargers registered at all.

    plan = tools.plan_charging_route("Home", "Far City", 90)

    assert "error" in plan
    assert "fast charger" in plan["error"]


def test_recursion_cap_prevents_infinite_planning(fake_maps):
    # Extreme consumption (1000 Wh/mi -> ~60 mile hops) and a 2000-mile trip:
    # the destination cannot be reached within MAX_CHARGING_STOPS.
    fake_maps.add_location("Home", 0)
    fake_maps.add_location("Far Far Away", 2000)
    for marker in range(50, 2000, 50):
        fake_maps.add_charger(f"Charger {marker}", marker)

    plan = tools._plan_charging_route("Home", "Far Far Away", 90, flat_override=1000.0)

    assert "error" in plan
    assert str(tools.MAX_CHARGING_STOPS) in plan["error"]


def test_route_error_propagates(fake_maps, monkeypatch):
    import maps_client

    def failing_route(origin, destination):
        return {"error": "No route found"}

    monkeypatch.setattr(maps_client, "compute_route", failing_route)
    plan = tools.plan_charging_route("Home", "Nowhere", 90)
    assert plan == {"error": "No route found"}


def test_elevation_failure_falls_back_with_note(fake_maps, monkeypatch):
    import maps_client

    def failing_elevations(points):
        raise RuntimeError("Elevation API error: OVER_QUERY_LIMIT")

    monkeypatch.setattr(maps_client, "get_elevations", failing_elevations)
    fake_maps.add_location("Home", 0)
    fake_maps.add_location("Nearby Town", 100)

    plan = tools.plan_charging_route("Home", "Nearby Town", 80)

    assert_plan_invariants(plan)
    # Flat 300 Wh/mile fallback: 100 mi -> 40% used instead of 37.3%.
    assert plan["segments"][0]["avg_consumption_wh_per_mile"] == pytest.approx(300, abs=1)
    assert plan["notes"] and "Elevation" in plan["notes"][0]
