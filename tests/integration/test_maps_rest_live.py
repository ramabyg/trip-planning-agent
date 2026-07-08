"""Live Routes/Places/Elevation REST calls used by the deterministic charging planner."""
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


def test_find_fast_chargers_in_santa_clara():
    chargers = maps_client.find_fast_chargers_near(37.35, -121.95, 20000, min_kw=100.0)
    assert chargers, "expected at least one >=100 kW DC fast charger near Santa Clara"
    first = chargers[0]
    assert first["lat"] and first["lng"] and first["name"]
    # The evOptions filter guarantees a fast connector; kW metadata should follow.
    assert any(c.get("max_kw") and c["max_kw"] >= 100 for c in chargers)


def test_find_amenities_near_downtown():
    amenities = maps_client.find_amenities_near(37.3541, -121.9552, 500)
    assert isinstance(amenities, list)
    assert amenities, "expected shops/restaurants near downtown Santa Clara"


def test_elevation_profile_over_a_mountain_pass():
    # Teton Pass (~2,570 m) vs. Driggs, ID (~1,860 m): the sampled profile
    # along a straight line between them must show a meaningful climb.
    points = [(43.7231, -111.1113), (43.4967, -110.9550)]
    dense = [(points[0][0] + (points[1][0] - points[0][0]) * i / 50,
              points[0][1] + (points[1][1] - points[0][1]) * i / 50)
             for i in range(51)]
    elevations = maps_client.get_elevations(dense)
    assert len(elevations) == len(dense)
    assert max(elevations) - min(elevations) > 200


def test_polyline_roundtrip_against_live_route():
    route = maps_client.compute_route("Santa Clara, CA", "San Jose, CA")
    points = route["polyline_points"]
    decoded = maps_client.decode_polyline(maps_client.encode_polyline(points))
    assert len(decoded) == len(points)
    assert decoded[0] == pytest.approx(points[0], abs=1e-4)
    assert decoded[-1] == pytest.approx(points[-1], abs=1e-4)
