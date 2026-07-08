"""Direct Google Maps REST access for deterministic planning code.

The LLM-facing Maps MCP toolset (tools.get_maps_mcp_toolset) is for the agents;
this module is for Python code (plan_charging_route) that must call Maps itself.
All network I/O for the charging planner is isolated here so tests can mock
this module alone. Uses the same MAPS_API_KEY as the MCP toolset.
"""
import json
import logging
import math
import os
import urllib.parse
import urllib.request

_flow = logging.getLogger("flow")  # configured by flow_log.py when enabled

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
PLACES_NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"
ELEVATION_URL = "https://maps.googleapis.com/maps/api/elevation/json"

METERS_PER_MILE = 1609.344

# Connector types the 2023 Model Y LR can use (Tesla native + CCS1 via adapter).
EV_CONNECTOR_TYPES = ["EV_CONNECTOR_TYPE_CCS_COMBO_1", "EV_CONNECTOR_TYPE_TESLA"]

# Amenity place types that indicate shops/restrooms/people near a charger.
AMENITY_TYPES = ["restaurant", "cafe", "convenience_store", "supermarket",
                 "gas_station", "shopping_mall"]

MAX_ELEVATION_SAMPLES = 512  # Elevation API hard limit per request


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

    _flow.info("      maps REST computeRoutes %s -> %s", origin, destination)
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


def find_fast_chargers_near(lat: float, lng: float, radius_m: float,
                            min_kw: float = 100.0) -> list:
    """Finds DC fast chargers (Tesla or CCS1) near a point via Places Text Search.

    Filters server-side by connector type and minimum charge rate, and returns
    real-time availability where the charging network reports it to Google.
    Each result: {"name", "address", "lat", "lng", "max_kw", "connector_count",
    "available_count", "out_of_service_count"} — the last two are None when the
    station does not report live status.
    """
    _flow.info("      maps REST places:searchText EV chargers >=%.0fkW near %.3f,%.3f",
               min_kw, lat, lng)
    payload = {
        "textQuery": "EV charging station",
        "includedType": "electric_vehicle_charging_station",
        "locationBias": {
            "circle": {
                "center": {"latitude": lat, "longitude": lng},
                "radius": min(radius_m, 50000.0),  # API max bias radius
            }
        },
        "evOptions": {
            "minimumChargingRateKw": min_kw,
            "connectorTypes": EV_CONNECTOR_TYPES,
        },
    }
    data = _post_json(
        PLACES_URL, payload,
        "places.displayName,places.formattedAddress,places.location,places.evChargeOptions",
    )
    results = []
    for place in data.get("places", []):
        loc = place.get("location", {})
        ev = place.get("evChargeOptions", {})
        max_kw = 0.0
        connector_count = 0
        available = None
        out_of_service = None
        for agg in ev.get("connectorAggregation", []):
            if agg.get("type") not in EV_CONNECTOR_TYPES:
                continue
            max_kw = max(max_kw, float(agg.get("maxChargeRateKw", 0.0)))
            connector_count += int(agg.get("count", 0))
            if "availableCount" in agg:
                available = (available or 0) + int(agg["availableCount"])
            if "outOfServiceCount" in agg:
                out_of_service = (out_of_service or 0) + int(agg["outOfServiceCount"])
        results.append({
            "name": place.get("displayName", {}).get("text", "EV charging station"),
            "address": place.get("formattedAddress", ""),
            "lat": loc.get("latitude"),
            "lng": loc.get("longitude"),
            "max_kw": max_kw or None,
            "connector_count": connector_count or None,
            "available_count": available,
            "out_of_service_count": out_of_service,
        })
    return results


def find_amenities_near(lat: float, lng: float, radius_m: float = 250.0) -> list:
    """Names of shops/food places within walking distance of a charger.

    Proxy for "not an isolated stop": restrooms, food, and people nearby.
    """
    _flow.info("      maps REST places:searchNearby amenities near %.3f,%.3f", lat, lng)
    payload = {
        "includedTypes": AMENITY_TYPES,
        "maxResultCount": 5,
        "locationRestriction": {
            "circle": {
                "center": {"latitude": lat, "longitude": lng},
                "radius": radius_m,
            }
        },
    }
    data = _post_json(PLACES_NEARBY_URL, payload, "places.displayName")
    return [p.get("displayName", {}).get("text", "") for p in data.get("places", [])
            if p.get("displayName", {}).get("text")]


def get_elevations(points: list) -> list:
    """Elevations (meters) sampled along a polyline via the Elevation API.

    Downsamples to the API's 512-point limit, sends the path as an encoded
    polyline, and returns one elevation per requested sample (same count as the
    downsampled path). Raises on API-level errors so callers can fall back.
    """
    path_points = downsample(points, MAX_ELEVATION_SAMPLES)
    _flow.info("      maps REST elevation (%d samples along route)", len(path_points))
    encoded = urllib.parse.quote(encode_polyline(path_points), safe="")
    url = (f"{ELEVATION_URL}?path=enc:{encoded}&samples={len(path_points)}"
           f"&key={_api_key()}")
    with urllib.request.urlopen(url, timeout=30) as response:
        data = json.loads(response.read().decode())
    if data.get("status") != "OK":
        raise RuntimeError(f"Elevation API error: {data.get('status')}")
    return [r["elevation"] for r in data.get("results", [])]


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


def encode_polyline(points: list) -> str:
    """Encodes (lat, lng) tuples into a Google encoded polyline (inverse of decode_polyline)."""
    def encode_value(delta: int) -> str:
        value = ~(delta << 1) if delta < 0 else delta << 1
        chunks = []
        while value >= 0x20:
            chunks.append(chr((0x20 | (value & 0x1F)) + 63))
            value >>= 5
        chunks.append(chr(value + 63))
        return "".join(chunks)

    encoded = []
    prev_lat = prev_lng = 0
    for lat, lng in points:
        lat_e5, lng_e5 = round(lat * 1e5), round(lng * 1e5)
        encoded.append(encode_value(lat_e5 - prev_lat))
        encoded.append(encode_value(lng_e5 - prev_lng))
        prev_lat, prev_lng = lat_e5, lng_e5
    return "".join(encoded)


def downsample(points: list, max_points: int) -> list:
    """Evenly downsamples a point list to at most max_points, keeping both endpoints."""
    if len(points) <= max_points:
        return list(points)
    step = (len(points) - 1) / (max_points - 1)
    return [points[round(i * step)] for i in range(max_points)]


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
