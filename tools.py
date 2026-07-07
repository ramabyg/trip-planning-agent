import os
import re
import yaml
import json
import datetime
import urllib.request
from google.cloud import storage
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams

import maps_client
from schemas import ChargingPlan

MAPS_MCP_URL = "https://mapstools.googleapis.com/mcp"

SPEC_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "specs", "01-trip-context.md")

# Fixed facts from specs/01-trip-context.md
TRIP_START = datetime.date(2026, 7, 18)
TRIP_END = datetime.date(2026, 7, 25)

# Vehicle constants (specs/02-charging-agent.md)
BATTERY_CAPACITY_KWH = 75.0
DEFAULT_CONSUMPTION_WH_PER_MILE = 280.0
MOUNTAIN_CONSUMPTION_WH_PER_MILE = 320.0
DEFAULT_SAFETY_BUFFER_SOC = 10
CHARGE_TARGET_SOC = 80
MAX_CHARGING_STOPS = 6
CHARGER_SEARCH_RADIUS_M = 40000.0


def get_maps_mcp_toolset(tool_filter: list | None = None):
    """
    Exposes Google Maps MCP tools (search_places, compute_routes, lookup_weather) to the LLM agent.
    Pass tool_filter to scope the toolset to only the tools an agent needs.
    """
    # Load env manually in case it hasn't been loaded yet
    from dotenv import load_dotenv
    load_dotenv()
    maps_api_key = os.getenv('MAPS_API_KEY', 'no_api_found')

    # The Google Maps MCP endpoint speaks streamable HTTP, not SSE — an SSE
    # connection fails with 405 Method Not Allowed (caught by
    # tests/integration/test_maps_mcp_live.py).
    tools = McpToolset(
        connection_params=StreamableHTTPConnectionParams(
            url=MAPS_MCP_URL,
            headers={
                "X-Goog-Api-Key": maps_api_key
            },
            timeout=30.0,
            sse_read_timeout=300.0
        ),
        tool_filter=tool_filter
    )

    return tools


# --- Trip context (fixed facts) ---

def _parse_context() -> dict:
    """Parses the YAML block in specs/01-trip-context.md (the source of truth)."""
    if not os.path.exists(SPEC_PATH):
        raise FileNotFoundError(f"Trip context spec not found at {SPEC_PATH}")
    with open(SPEC_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    match = re.search(r"```yaml\n(.*?)\n```", content, re.DOTALL)
    if not match:
        raise ValueError(f"No YAML block found in {SPEC_PATH}")
    return yaml.safe_load(match.group(1))


def trip_day_index(date: datetime.date) -> int:
    """Day of the trip, 1 (Jul 18) through 8 (Jul 25). Raises for dates outside the trip."""
    if date < TRIP_START or date > TRIP_END:
        raise ValueError(f"{date.isoformat()} is outside the trip range "
                         f"({TRIP_START.isoformat()} to {TRIP_END.isoformat()})")
    return (date - TRIP_START).days + 1


def current_base(date: datetime.date, context: dict | None = None) -> list:
    """Accommodation record(s) covering the given night (checkin <= date < checkout)."""
    context = context if context is not None else _parse_context()
    bases = []
    for acc in context.get("accommodations", []):
        checkin = datetime.date.fromisoformat(str(acc["dates"][0]))
        checkout = datetime.date.fromisoformat(str(acc["dates"][1]))
        if checkin <= date < checkout:
            bases.append(acc)
    return bases


def is_group_together(date: datetime.date, context: dict | None = None) -> bool:
    """True when all three families share one lodging for the given night."""
    bases = current_base(date, context)
    if len(bases) != 1 or bases[0].get("type") == "none":
        return False
    return len(bases[0].get("occupants", [])) >= 3


def get_trip_context(date: str) -> dict:
    """
    Returns the fixed trip context grounded to a specific date: the trip day index,
    that night's lodging (one record, or two when the group is split), whether the
    families are together, plus the full raw trip data.

    Args:
        date: The date to ground against, in YYYY-MM-DD format (trip range is
              2026-07-18 to 2026-07-25).
    """
    try:
        context = _parse_context()
    except Exception as e:
        return {"error": f"Failed to parse trip context: {str(e)}"}

    try:
        day = datetime.date.fromisoformat(date)
    except ValueError:
        return {"error": f"Invalid date '{date}'. Use YYYY-MM-DD format."}

    result = {"date": date}
    try:
        result["trip_day_index"] = trip_day_index(day)
        result["current_base"] = current_base(day, context)
        result["is_group_together"] = is_group_together(day, context)
    except ValueError as e:
        result["warning"] = str(e)

    result["trip"] = context.get("trip")
    result["accommodations"] = context.get("accommodations")
    return result


# --- Tesla range math (deterministic) ---

def calculate_tesla_segments(
    distance_miles: float,
    current_soc: int,
    consumption_rate_wh_per_mile: float = DEFAULT_CONSUMPTION_WH_PER_MILE,
    safety_buffer_soc: int = DEFAULT_SAFETY_BUFFER_SOC,
) -> dict:
    """
    Calculates Tesla Model Y Long Range battery consumption for a drive segment.

    Args:
        distance_miles: The distance of the drive segment in miles.
        current_soc: The current battery state of charge (SOC) percentage (10 to 100).
        consumption_rate_wh_per_mile: Energy use per mile; 280 typical highway,
            320 for mountain passes / heavy climate load.
        safety_buffer_soc: Minimum SOC to preserve on arrival.

    Returns:
        A dictionary with reachability, energy needed, projected arrival SOC, and recommendations.
    """
    consumption_kwh_per_mile = consumption_rate_wh_per_mile / 1000.0

    energy_needed_kwh = distance_miles * consumption_kwh_per_mile
    soc_needed = (energy_needed_kwh / BATTERY_CAPACITY_KWH) * 100.0

    projected_arrival_soc = current_soc - soc_needed
    reachable = projected_arrival_soc >= safety_buffer_soc

    max_range_at_current_soc = ((current_soc - safety_buffer_soc) / 100.0) * (BATTERY_CAPACITY_KWH / consumption_kwh_per_mile)

    result = {
        "segment_distance_miles": round(distance_miles, 1),
        "starting_soc": current_soc,
        "energy_needed_kwh": round(energy_needed_kwh, 2),
        "soc_needed_percent": round(soc_needed, 1),
        "projected_arrival_soc": round(projected_arrival_soc, 1),
        "reachable": reachable,
        "max_range_before_charge": round(max_range_at_current_soc, 1),
        "safety_buffer_soc": safety_buffer_soc,
        "consumption_rate_wh_per_mile": consumption_rate_wh_per_mile,
    }

    if reachable:
        result["recommendation"] = "Reachable directly. No charging stop required for this segment."
    else:
        result["recommendation"] = f"Warning: Target location is out of range. You need to charge. Your maximum range is {round(max_range_at_current_soc, 1)} miles. Suggest searching for a 'Tesla Supercharger' along the route before this limit."

    return result


def _select_charging_stop(start: str, polyline_points: list, current_soc: int,
                          consumption_rate_wh_per_mile: float) -> dict | None:
    """Finds the best on-route Supercharger reachable from `start` with the buffer intact.

    Candidates are searched near the max-range point on the route polyline and
    ranked by distance from the route (a cheap detour proxy). Returns the leg
    info for the chosen charger, or None when nothing feasible is found.
    """
    calc = calculate_tesla_segments(0, current_soc, consumption_rate_wh_per_mile)
    max_range = calc["max_range_before_charge"]
    start_point = polyline_points[0]

    candidates = []
    # Search slightly before the hard range limit; fall back to earlier on the route.
    for fraction in (0.9, 0.6):
        sample = maps_client.point_at_distance(polyline_points, max_range * fraction)
        candidates = maps_client.find_superchargers_near(sample[0], sample[1], CHARGER_SEARCH_RADIUS_M)
        if candidates:
            break
    if not candidates:
        return None

    candidates.sort(key=lambda c: maps_client.distance_to_polyline_miles((c["lat"], c["lng"]), polyline_points))

    for candidate in candidates[:3]:
        # Skip chargers at (or behind) the starting point — no forward progress.
        if maps_client.haversine_miles(start_point, (candidate["lat"], candidate["lng"])) < 1.0:
            continue
        leg = maps_client.compute_route(start, f"{candidate['lat']},{candidate['lng']}")
        if "error" in leg:
            continue
        leg_calc = calculate_tesla_segments(leg["distance_miles"], current_soc, consumption_rate_wh_per_mile)
        if leg_calc["reachable"]:
            return {
                "charger": candidate,
                "distance_miles": leg["distance_miles"],
                "duration_minutes": leg["duration_minutes"],
                "arrival_soc": leg_calc["projected_arrival_soc"],
            }
    return None


def plan_charging_route(origin: str, destination: str, current_soc: int,
                        consumption_rate_wh_per_mile: float) -> dict:
    """
    Plans the full EV driving route from origin to destination, inserting Tesla
    Supercharger stops wherever the destination is beyond safe range. The whole
    algorithm is deterministic: routing, charger search, and SOC math all happen
    in code, so identical inputs always give the identical plan.

    Args:
        origin: Starting location (address or "lat,lng").
        destination: Final destination (address or "lat,lng").
        current_soc: Battery state of charge at departure (10-100).
        consumption_rate_wh_per_mile: 280 for typical highway driving; use 320
            for mountain passes or heavy climate-control load.

    Returns:
        A dict matching the ChargingPlan schema, or {"error": ...} when no safe
        plan exists.
    """
    segments = []
    start = origin
    soc = float(current_soc)

    for _ in range(MAX_CHARGING_STOPS + 1):
        route = maps_client.compute_route(start, destination)
        if "error" in route:
            return {"error": route["error"]}

        calc = calculate_tesla_segments(route["distance_miles"], soc, consumption_rate_wh_per_mile)
        if calc["reachable"]:
            segments.append({
                "start": start,
                "end": destination,
                "distance_miles": round(route["distance_miles"], 1),
                "duration_minutes": round(route["duration_minutes"], 1),
                "departure_soc": int(round(soc)),
                "arrival_soc": int(round(calc["projected_arrival_soc"])),
                "action": "Arrive at destination",
            })
            plan = {
                "directly_reachable": len(segments) == 1,
                "total_distance_miles": round(sum(s["distance_miles"] for s in segments), 1),
                "total_duration_minutes": round(sum(s["duration_minutes"] for s in segments), 1),
                "segments": segments,
            }
            return ChargingPlan(**plan).model_dump()

        stop = _select_charging_stop(start, route["polyline_points"], int(round(soc)),
                                     consumption_rate_wh_per_mile)
        if stop is None:
            return {"error": f"No reachable Tesla Supercharger found within "
                             f"{calc['max_range_before_charge']} miles along the route from '{start}'. "
                             f"Charge to a higher SOC before departing, or plan a different route."}

        charger = stop["charger"]
        segments.append({
            "start": start,
            "end": f"{charger['name']} ({charger['address']})",
            "distance_miles": round(stop["distance_miles"], 1),
            "duration_minutes": round(stop["duration_minutes"], 1),
            "departure_soc": int(round(soc)),
            "arrival_soc": int(round(stop["arrival_soc"])),
            "action": f"Charge to {CHARGE_TARGET_SOC}%",
        })
        start = f"{charger['lat']},{charger['lng']}"
        soc = float(CHARGE_TARGET_SOC)

    return {"error": f"Charging plan exceeded {MAX_CHARGING_STOPS} stops without reaching "
                     f"'{destination}'. Check the origin/destination inputs."}


# --- NPS alerts ---

def get_nps_alerts(park_name: str) -> list:
    """
    Retrieves active alerts and road/trail closures for the given National Park.
    Uses the NPS API if NPS_API_KEY is defined in environment, otherwise falls back to mock alerts.
    Every alert carries a "source" field: "live" (real NPS data) or "mock" (simulated).

    Args:
        park_name: Name of the park ('Yellowstone', 'Grand Teton', or 'Glacier').
    """
    from dotenv import load_dotenv
    load_dotenv()

    park_mappings = {
        "yellowstone": "yell",
        "grand teton": "grte",
        "glacier": "glac"
    }

    name_lower = park_name.lower().strip()
    park_code = None
    for k, v in park_mappings.items():
        if k in name_lower:
            park_code = v
            break

    if not park_code:
        return [{"title": "Unknown Park", "description": f"No alert mapping for park name: '{park_name}'", "source": "mock"}]

    nps_api_key = os.getenv("NPS_API_KEY")

    # Mock Alerts dataset
    mock_alerts = {
        "yell": [
            {
                "title": "Tower-Roosevelt to Canyon Road Mudslide Closure",
                "description": "The road between Tower Junction and Canyon Village is closed due to recent mudslides. Detours are in place via Norris Junction.",
                "category": "Danger"
            },
            {
                "title": "Grand Canyon of the Yellowstone North Rim Trail Restriction",
                "description": "Portions of the North Rim Trail are closed for boardwalk restoration. Expect minor delays and trail rerouting near Lookout Point.",
                "category": "Caution"
            }
        ],
        "grte": [
            {
                "title": "Signal Mountain Summit Road Repairs",
                "description": "Signal Mountain Road is closed daily from 8 AM to 4 PM for asphalt repairs. Scenic overlooks are inaccessible during these hours.",
                "category": "Information"
            },
            {
                "title": "Jenny Lake Ferry Construction Delay",
                "description": "The west shore boat dock is undergoing maintenance. Ferry services are operational but expect longer boarding queues.",
                "category": "Caution"
            }
        ],
        "glac": [
            {
                "title": "Highline Trail Temporary Grizzly Closure",
                "description": "Highline Trail is temporarily closed from Logan Pass to Granite Park Chalet due to an active grizzly bear carcass encounter.",
                "category": "Danger"
            },
            {
                "title": "Many Glacier Road Timed Entry Permits",
                "description": "Timed entry reservation is required to enter the Many Glacier valley between 6 AM and 3 PM. Plan accordingly.",
                "category": "Caution"
            }
        ]
    }

    def tagged_mock(code: str) -> list:
        return [dict(alert, source="mock") for alert in mock_alerts.get(code, [])]

    if not nps_api_key or nps_api_key == "YOUR_NPS_API_KEY" or nps_api_key.strip() == "":
        print(f"Using mock alerts for park code: {park_code}")
        return tagged_mock(park_code)

    try:
        url = f"https://developer.nps.gov/api/v1/alerts?parkCode={park_code}"
        req = urllib.request.Request(
            url,
            headers={"X-Api-Key": nps_api_key}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            res_data = json.loads(response.read().decode())
            raw_alerts = res_data.get("data", [])

            parsed_alerts = []
            for alert in raw_alerts:
                parsed_alerts.append({
                    "title": alert.get("title"),
                    "description": alert.get("description"),
                    "category": alert.get("category", "Warning"),
                    "source": "live"
                })
            return parsed_alerts
    except Exception as e:
        print(f"Error fetching NPS alerts: {e}. Falling back to mock alerts.")
        return tagged_mock(park_code)


def save_and_upload_trip_plan(day_index: int, day_title: str, plan_markdown: str) -> str:
    """
    Saves the daily trip itinerary locally and uploads it to Google Cloud Storage.
    Generates a 24-hour signed URL for the uploaded file.

    Args:
        day_index: Index of the trip day (e.g. 1 for Day 1).
        day_title: Title description of the day (e.g. 'Santa Clara to Elko').
        plan_markdown: Formatted markdown content of the day's itinerary.
    """
    from dotenv import load_dotenv
    load_dotenv()
    project_id = os.getenv('GOOGLE_CLOUD_PROJECT', 'project_not_set')
    bucket_name = f"yellowstone-trip-data-{project_id}"

    # Save locally to temp/tmp directory first
    current_dir = os.path.dirname(os.path.abspath(__file__))
    tmp_dir = os.path.join(current_dir, "tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    filename = f"day_{day_index}_plan.md"
    local_path = os.path.join(tmp_dir, filename)

    header = f"# Trip Itinerary: Day {day_index} - {day_title}\n"
    header += f"*Generated on {datetime.date.today().isoformat()}*\n\n"

    full_content = header + plan_markdown

    with open(local_path, "w", encoding="utf-8") as f:
        f.write(full_content)

    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)

        # Check if bucket exists, create if not
        if not bucket.exists():
            bucket = storage_client.create_bucket(bucket_name, location="us-west1")

        blob = bucket.blob(filename)
        blob.upload_from_filename(local_path)

        # Generate a signed URL valid for 24 hours
        url = blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(hours=24),
            method="GET",
        )
        return url
    except Exception as e:
        print(f"Error uploading plan to GCS: {e}")
        # Return local path prefix if GCS upload fails (so frontend resolves it)
        return f"/tmp/{filename}"
