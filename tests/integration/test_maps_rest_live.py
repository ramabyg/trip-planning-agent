"""Live Routes/Places REST calls used by the deterministic charging planner."""
import os

import pytest

import maps_client

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("MAPS_API_KEY"), reason="MAPS_API_KEY not set"),
]


def test_compute_route_santa_clara_to_sacramento():
    route = maps_client.compute_route("Santa Clara, CA", "Sacramento, CA")
    assert "error" not in route
    # ~120 miles by road; generous band tolerates alternate routings.
    assert 100 <= route["distance_miles"] <= 160
    assert route["duration_minutes"] > 60
    assert len(route["polyline_points"]) > 10


def test_find_superchargers_in_santa_clara():
    chargers = maps_client.find_superchargers_near(37.35, -121.95, 20000)
    assert chargers, "expected at least one Supercharger near Santa Clara"
    first = chargers[0]
    assert first["lat"] and first["lng"] and first["name"]
