"""Shared fixtures for the trip-planning-agent test suite."""
import pytest

import maps_client

# Derived from the same haversine the production code uses, so fake-world mile
# markers agree exactly with the distances the planner computes.
MILES_PER_DEG_LAT = maps_client.haversine_miles((0.0, 0.0), (1.0, 0.0))


class FakeMaps:
    """Synthetic road network replacing maps_client's network calls.

    Locations and chargers are placed at mile markers along a north-south line
    (longitude 0); routes are straight-line haversine distances at 1 minute per
    mile with a 100-point interpolated polyline. Geometry helpers from
    maps_client are reused unpatched, so planner math behaves as in production.
    """

    def __init__(self):
        self.locations = {}
        self.chargers = []

    def add_location(self, name: str, mile_marker: float, lng: float = 0.0):
        self.locations[name] = (mile_marker / MILES_PER_DEG_LAT, lng)

    def add_charger(self, name: str, mile_marker: float, lng: float = 0.0):
        self.chargers.append({
            "name": name,
            "address": f"{name}, Fake Highway 1",
            "lat": mile_marker / MILES_PER_DEG_LAT,
            "lng": lng,
        })

    def _resolve(self, value: str) -> tuple:
        if value in self.locations:
            return self.locations[value]
        lat, lng = value.split(",")
        return (float(lat), float(lng))

    def compute_route(self, origin: str, destination: str) -> dict:
        a, b = self._resolve(origin), self._resolve(destination)
        distance = maps_client.haversine_miles(a, b)
        n = 100
        points = [(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n)
                  for i in range(n + 1)]
        return {
            "distance_miles": distance,
            "duration_minutes": distance,
            "polyline_points": points,
        }

    def find_superchargers_near(self, lat: float, lng: float, radius_m: float) -> list:
        radius_miles = radius_m / 1609.344
        return [dict(c) for c in self.chargers
                if maps_client.haversine_miles((lat, lng), (c["lat"], c["lng"])) <= radius_miles]


@pytest.fixture
def fake_maps(monkeypatch):
    fake = FakeMaps()
    monkeypatch.setattr(maps_client, "compute_route", fake.compute_route)
    monkeypatch.setattr(maps_client, "find_superchargers_near", fake.find_superchargers_near)
    return fake
