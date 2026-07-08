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
    mile with a 100-point interpolated polyline. Terrain is flat unless hills
    are added with set_hill; chargers default to live-available, 150 kW, with
    one amenity nearby. Geometry helpers from maps_client are reused unpatched,
    so planner math behaves as in production.
    """

    def __init__(self):
        self.locations = {}
        self.chargers = []
        self.hills = []

    def add_location(self, name: str, mile_marker: float, lng: float = 0.0):
        self.locations[name] = (mile_marker / MILES_PER_DEG_LAT, lng)

    def add_charger(self, name: str, mile_marker: float, lng: float = 0.0,
                    max_kw: float = 150.0, available_count: int | None = 4,
                    amenities: list | None = None):
        self.chargers.append({
            "name": name,
            "address": f"{name}, Fake Highway 1",
            "lat": mile_marker / MILES_PER_DEG_LAT,
            "lng": lng,
            "max_kw": max_kw,
            "connector_count": 8,
            "available_count": available_count,
            "out_of_service_count": 0,
            "_amenities": list(amenities) if amenities is not None else ["Fake Diner"],
        })

    def set_hill(self, start_mile: float, end_mile: float, peak_m: float):
        """Adds a triangular hill: 0 m at start/end, peak_m at the midpoint."""
        self.hills.append((start_mile, end_mile, peak_m))

    def elevation_at_mile(self, mile: float) -> float:
        elevation = 0.0
        for start, end, peak in self.hills:
            mid = (start + end) / 2.0
            if start <= mile <= mid:
                elevation += peak * (mile - start) / (mid - start)
            elif mid < mile <= end:
                elevation += peak * (end - mile) / (end - mid)
        return elevation

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

    def find_fast_chargers_near(self, lat: float, lng: float, radius_m: float,
                                min_kw: float = 100.0) -> list:
        radius_miles = radius_m / 1609.344
        return [{k: v for k, v in c.items() if not k.startswith("_")}
                for c in self.chargers
                if (c["max_kw"] or 0) >= min_kw
                and maps_client.haversine_miles((lat, lng), (c["lat"], c["lng"])) <= radius_miles]

    def find_amenities_near(self, lat: float, lng: float, radius_m: float = 250.0) -> list:
        for c in self.chargers:
            if maps_client.haversine_miles((lat, lng), (c["lat"], c["lng"])) < 0.1:
                return list(c["_amenities"])
        return []

    def get_elevations(self, points: list) -> list:
        return [self.elevation_at_mile(p[0] * MILES_PER_DEG_LAT) for p in points]


@pytest.fixture
def fake_maps(monkeypatch):
    fake = FakeMaps()
    monkeypatch.setattr(maps_client, "compute_route", fake.compute_route)
    monkeypatch.setattr(maps_client, "find_fast_chargers_near", fake.find_fast_chargers_near)
    monkeypatch.setattr(maps_client, "find_amenities_near", fake.find_amenities_near)
    monkeypatch.setattr(maps_client, "get_elevations", fake.get_elevations)
    return fake
