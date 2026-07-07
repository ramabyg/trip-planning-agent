"""Direct Google Maps REST access for deterministic planning code.

The LLM-facing Maps MCP toolset (tools.get_maps_mcp_toolset) is for the agents;
this module is for Python code (plan_charging_route) that must call Maps itself.
All network I/O for the charging planner is isolated here so tests can mock
this module alone. Uses the same MAPS_API_KEY as the MCP toolset.
"""
import json
import math
import os
import urllib.request

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
PLACES_URL = "https://places.googleapis.com/v1/places:searchText"

METERS_PER_MILE = 1609.344


def _api_key() -> str:
    from dotenv import load_dotenv
    load_dotenv()
    return os.getenv("MAPS_API_KEY", "no_api_key_found")


def _post_json(url: str, payload: dict, field_mask: str) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": _api_key(),
            "X-Goog-FieldMask": field_mask,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode())


def compute_route(origin: str, destination: str) -> dict:
    """Computes a driving route via the Routes API v2.

    Origin/destination are free-form addresses or "lat,lng" strings.
    Returns {"distance_miles", "duration_minutes", "polyline_points"} where
    polyline_points is a list of (lat, lng) tuples along the route.
    """
    def waypoint(value: str) -> dict:
        parts = value.split(",")
        if len(parts) == 2:
            try:
                lat, lng = float(parts[0]), float(parts[1])
                return {"location": {"latLng": {"latitude": lat, "longitude": lng}}}
            except ValueError:
                pass
        return {"address": value}

    payload = {
        "origin": waypoint(origin),
        "destination": waypoint(destination),
        "travelMode": "DRIVE",
    }
    data = _post_json(
        ROUTES_URL, payload,
        "routes.distanceMeters,routes.duration,routes.polyline.encodedPolyline",
    )
    routes = data.get("routes", [])
    if not routes:
        return {"error": f"No route found from '{origin}' to '{destination}'"}
    route = routes[0]
    duration_s = float(str(route.get("duration", "0s")).rstrip("s"))
    encoded = route.get("polyline", {}).get("encodedPolyline", "")
    return {
        "distance_miles": route["distanceMeters"] / METERS_PER_MILE,
        "duration_minutes": duration_s / 60.0,
        "polyline_points": decode_polyline(encoded),
    }


def find_superchargers_near(lat: float, lng: float, radius_m: float) -> list:
    """Finds Tesla Superchargers near a point via Places Text Search.

    Returns a list of {"name", "address", "lat", "lng"} dicts.
    """
    payload = {
        "textQuery": "Tesla Supercharger",
        "locationBias": {
            "circle": {
                "center": {"latitude": lat, "longitude": lng},
                "radius": min(radius_m, 50000.0),  # API max bias radius
            }
        },
    }
    data = _post_json(
        PLACES_URL, payload,
        "places.displayName,places.formattedAddress,places.location",
    )
    results = []
    for place in data.get("places", []):
        loc = place.get("location", {})
        results.append({
            "name": place.get("displayName", {}).get("text", "Tesla Supercharger"),
            "address": place.get("formattedAddress", ""),
            "lat": loc.get("latitude"),
            "lng": loc.get("longitude"),
        })
    return results


# --- Pure geometry helpers (no network) ---

def decode_polyline(encoded: str) -> list:
    """Decodes a Google encoded polyline into a list of (lat, lng) tuples."""
    points = []
    index = lat = lng = 0
    while index < len(encoded):
        for is_lng in (False, True):
            shift, result = 0, 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if is_lng:
                lng += delta
            else:
                lat += delta
        points.append((lat / 1e5, lng / 1e5))
    return points


def haversine_miles(a: tuple, b: tuple) -> float:
    """Great-circle distance in miles between two (lat, lng) points."""
    lat1, lng1, lat2, lng2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2)
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def point_at_distance(points: list, target_miles: float) -> tuple:
    """Walks a polyline and returns the first point at/past target_miles.

    Falls back to the last point if the polyline is shorter than the target.
    """
    if not points:
        raise ValueError("empty polyline")
    traveled = 0.0
    for prev, cur in zip(points, points[1:]):
        traveled += haversine_miles(prev, cur)
        if traveled >= target_miles:
            return cur
    return points[-1]


def distance_to_polyline_miles(point: tuple, points: list) -> float:
    """Minimum distance from a point to any vertex of a polyline (detour proxy)."""
    return min(haversine_miles(point, p) for p in points)
