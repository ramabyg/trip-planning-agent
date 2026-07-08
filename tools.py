import os
import re
import math
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

# Vehicle & planning constants (specs/02-charging-agent.md)
BATTERY_CAPACITY_KWH = 75.0
DEFAULT_CONSUMPTION_WH_PER_MILE = 280.0
FALLBACK_CONSUMPTION_WH_PER_MILE = 300.0  # flat rate when elevation data is unavailable
DEFAULT_SAFETY_BUFFER_SOC = 10
DEFAULT_CHARGE_TARGET_SOC = 80
MAX_CHARGE_TARGET_SOC = 95
CHARGE_MARGIN_SOC = 5  # headroom added on top of the buffer when sizing a charge
MAX_CHARGING_STOPS = 20  # runaway guard, not a planning constraint
CHARGER_SEARCH_RADIUS_M = 40000.0
MIN_CHARGER_POWER_KW = 100.0  # primary tier: avoid long dwell at slow chargers
FALLBACK_MIN_CHARGER_POWER_KW = 50.0  # last resort on sparse corridors
MAX_VEHICLE_CHARGE_KW = 250.0

# Elevation-adaptive energy model (per ~5-mile chunk of the route polyline).
# Regen is credited at only 40% recovery — deliberately conservative so range
# estimates err on the safe side.
ENERGY_CHUNK_MILES = 5.0
WH_PER_METER_CLIMB = 7.0
REGEN_RECOVERY = 0.40
WH_PER_METER_DESCENT_CREDIT = WH_PER_METER_CLIMB * REGEN_RECOVERY  # 2.8
MIN_CHUNK_WH_PER_MILE = 180.0
MAX_CHUNK_WH_PER_MILE = 550.0

# Piecewise Model Y LR charging curve: (from_soc, to_soc, avg_kw at a 250 kW station).
CHARGE_CURVE_BANDS = ((10, 55, 170.0), (55, 80, 95.0), (80, 95, 45.0))

# Fractions of the reachable-energy budget at which to search for chargers.
CHARGER_SEARCH_FRACTIONS = (0.95, 0.8, 0.65, 0.5, 0.35, 0.2)
CHARGER_CANDIDATES_TO_TRY = 5


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


# --- Elevation-adaptive energy model (pure, no network) ---

def build_energy_profile(points: list, elevations: list | None,
                         flat_rate_wh_per_mile: float | None = None) -> list:
    """Splits a route polyline into ~5-mile chunks with terrain-adjusted rates.

    `points` and `elevations` must be index-aligned. Each chunk carries
    {"points", "miles", "wh_per_mile", "kwh"}. Without elevations, every chunk
    uses flat_rate_wh_per_mile (280 base when that is None too).
    """
    if len(points) < 2:
        return []
    flat = flat_rate_wh_per_mile if elevations is None else None
    if elevations is None and flat is None:
        flat = DEFAULT_CONSUMPTION_WH_PER_MILE

    chunks = []
    chunk_points = [points[0]]
    chunk_miles = ascent_m = descent_m = 0.0
    for i in range(1, len(points)):
        chunk_points.append(points[i])
        chunk_miles += maps_client.haversine_miles(points[i - 1], points[i])
        if elevations is not None:
            delta = elevations[i] - elevations[i - 1]
            if delta > 0:
                ascent_m += delta
            else:
                descent_m -= delta
        if chunk_miles >= ENERGY_CHUNK_MILES or i == len(points) - 1:
            if chunk_miles > 0:
                if flat is not None:
                    rate = flat
                else:
                    rate = DEFAULT_CONSUMPTION_WH_PER_MILE + (
                        ascent_m * WH_PER_METER_CLIMB
                        - descent_m * WH_PER_METER_DESCENT_CREDIT) / chunk_miles
                    rate = min(MAX_CHUNK_WH_PER_MILE, max(MIN_CHUNK_WH_PER_MILE, rate))
                chunks.append({
                    "points": chunk_points,
                    "miles": chunk_miles,
                    "wh_per_mile": rate,
                    "kwh": chunk_miles * rate / 1000.0,
                })
            chunk_points = [points[i]]
            chunk_miles = ascent_m = descent_m = 0.0
    return chunks


def profile_energy_kwh(profile: list) -> float:
    return sum(c["kwh"] for c in profile)


def point_at_energy_budget(profile: list, budget_kwh: float) -> tuple:
    """Farthest polyline point reachable within the energy budget (conservative:
    stops at the last point fully inside the budget)."""
    if not profile:
        raise ValueError("empty energy profile")
    last = profile[0]["points"][0]
    remaining = budget_kwh
    for chunk in profile:
        if chunk["kwh"] <= remaining:
            remaining -= chunk["kwh"]
            last = chunk["points"][-1]
            continue
        kwh_per_mile = chunk["wh_per_mile"] / 1000.0
        pts = chunk["points"]
        for prev, cur in zip(pts, pts[1:]):
            step = maps_client.haversine_miles(prev, cur) * kwh_per_mile
            if step > remaining:
                return last
            remaining -= step
            last = cur
        return last
    return last


def estimate_charge_time_minutes(from_soc: float, to_soc: float,
                                 station_kw: float | None = None) -> float:
    """DC charge time from a piecewise Model Y LR curve, capped by station power.

    The 10-55% band scales with station power; upper bands are already below
    most stations' limits and are only clamped, never scaled up.
    """
    if to_soc <= from_soc:
        return 0.0
    power = min(station_kw or MAX_VEHICLE_CHARGE_KW, MAX_VEHICLE_CHARGE_KW)
    from_soc = max(from_soc, float(CHARGE_CURVE_BANDS[0][0]))
    minutes = 0.0
    for band_lo, band_hi, avg_kw in CHARGE_CURVE_BANDS:
        lo, hi = max(band_lo, from_soc), min(band_hi, to_soc)
        if hi <= lo:
            continue
        if band_lo == CHARGE_CURVE_BANDS[0][0]:
            rate = min(avg_kw * power / MAX_VEHICLE_CHARGE_KW, power)
        else:
            rate = min(avg_kw, power)
        energy_kwh = (hi - lo) / 100.0 * BATTERY_CAPACITY_KWH
        minutes += energy_kwh / rate * 60.0
    return minutes


def _leg_energy(route: dict, flat_override: float | None) -> tuple:
    """Energy analysis for one routed leg.

    Returns (profile, avg_wh_per_mile, soc_needed, fallback_note). Uses the
    Elevation API unless flat_override is given; falls back to a flat
    conservative rate (with a note) when elevation data is unavailable. Chunk
    mileage is rescaled to the Routes API distance so haversine shortfall on
    the downsampled polyline never under-counts energy.
    """
    points = route["polyline_points"]
    fallback_note = None
    if flat_override is not None:
        profile = build_energy_profile(points, None, flat_override)
    else:
        sampled = maps_client.downsample(points, maps_client.MAX_ELEVATION_SAMPLES)
        try:
            elevations = maps_client.get_elevations(sampled)
            profile = build_energy_profile(sampled, elevations)
        except Exception as e:
            fallback_note = (f"Elevation data unavailable ({e}); used a flat "
                             f"{FALLBACK_CONSUMPTION_WH_PER_MILE:.0f} Wh/mile estimate.")
            profile = build_energy_profile(points, None, FALLBACK_CONSUMPTION_WH_PER_MILE)

    route_miles = route["distance_miles"]
    profile_miles = sum(c["miles"] for c in profile)
    if profile and profile_miles > 0 and route_miles > 0:
        scale = route_miles / profile_miles
        for c in profile:
            c["miles"] *= scale
            c["kwh"] *= scale

    kwh = profile_energy_kwh(profile)
    soc_needed = kwh / BATTERY_CAPACITY_KWH * 100.0
    avg_rate = (kwh * 1000.0 / route_miles) if route_miles > 0 else 0.0
    return profile, avg_rate, soc_needed, fallback_note


# --- Charging stop selection ---

def _select_charging_stop(profile: list, departure_soc: float,
                          start: str, flat_override: float | None) -> dict | None:
    """Best on-route fast charger reachable from `start` with the buffer intact.

    Searches near sample points at fractions of the reachable-energy budget
    (≥100 kW first, ≥50 kW as a last resort), drops stations whose live status
    shows zero usable connectors, prefers live-confirmed and amenity-rich
    stops, then confirms feasibility on the actual routed leg.
    """
    budget_kwh = (departure_soc - DEFAULT_SAFETY_BUFFER_SOC) / 100.0 * BATTERY_CAPACITY_KWH
    if budget_kwh <= 0 or not profile:
        return None
    start_point = profile[0]["points"][0]
    route_points = [p for chunk in profile for p in chunk["points"]]

    def detour(c) -> float:
        return maps_client.distance_to_polyline_miles((c["lat"], c["lng"]), route_points)

    # Fractions are tried farthest-first and a feasible charger at a farther
    # fraction always wins: mixing all fractions into one pool would let a
    # low-detour charger right after the start win and the plan crawl forward
    # in tiny hops. The slow-charger tier only opens once every fraction has
    # failed at >=100 kW.
    rejected = set()
    for min_kw in (MIN_CHARGER_POWER_KW, FALLBACK_MIN_CHARGER_POWER_KW):
        for fraction in CHARGER_SEARCH_FRACTIONS:
            sample = point_at_energy_budget(profile, budget_kwh * fraction)
            candidates = []
            seen = set()
            for c in maps_client.find_fast_chargers_near(
                    sample[0], sample[1], CHARGER_SEARCH_RADIUS_M, min_kw):
                key = (round(c["lat"], 4), round(c["lng"], 4))
                if key in seen or key in rejected:
                    continue
                seen.add(key)
                # Confirmed dead/fully-occupied stations are useless; unknown
                # availability (no live feed) stays in, ranked lower below.
                if c.get("available_count") is not None and c["available_count"] <= 0:
                    continue
                # No forward progress from (or behind) the starting point.
                if maps_client.haversine_miles(start_point, (c["lat"], c["lng"])) < 1.0:
                    continue
                candidates.append(c)
            if not candidates:
                continue

            candidates.sort(key=lambda c: (c.get("available_count") is None, detour(c),
                                           -(c.get("max_kw") or 0.0)))
            shortlist = candidates[:CHARGER_CANDIDATES_TO_TRY]
            for c in shortlist:
                try:
                    c["amenities"] = maps_client.find_amenities_near(c["lat"], c["lng"])
                except Exception:
                    c["amenities"] = []
            shortlist.sort(key=lambda c: (c.get("available_count") is None,
                                          not c["amenities"], detour(c),
                                          -(c.get("max_kw") or 0.0)))

            for candidate in shortlist:
                leg = maps_client.compute_route(start, f"{candidate['lat']},{candidate['lng']}")
                if "error" in leg:
                    rejected.add((round(candidate["lat"], 4), round(candidate["lng"], 4)))
                    continue
                _, avg_rate, soc_needed, _ = _leg_energy(leg, flat_override)
                if departure_soc - soc_needed >= DEFAULT_SAFETY_BUFFER_SOC:
                    return {
                        "charger": candidate,
                        "distance_miles": leg["distance_miles"],
                        "duration_minutes": leg["duration_minutes"],
                        "soc_needed": soc_needed,
                        "avg_rate": avg_rate,
                    }
                rejected.add((round(candidate["lat"], 4), round(candidate["lng"], 4)))
    return None


def plan_charging_route(origin: str, destination: str, current_soc: int) -> dict:
    """
    Plans the full EV driving route from origin to destination, inserting DC
    fast-charging stops (Tesla Superchargers or CCS networks such as EVgo,
    Electrify America, ChargePoint) wherever the destination is beyond safe
    range. The whole algorithm is deterministic: routing, elevation-adjusted
    consumption, charger search, charge targets, and SOC math all happen in
    code, so identical inputs always give the identical plan.

    Args:
        origin: Starting location (address or "lat,lng").
        destination: Final destination (address or "lat,lng").
        current_soc: Battery state of charge at departure (10-100).

    Returns:
        A dict matching the ChargingPlan schema, or {"error": ...} when no safe
        plan exists.
    """
    return _plan_charging_route(origin, destination, current_soc)


def _plan_charging_route(origin: str, destination: str, current_soc: int,
                         flat_override: float | None = None) -> dict:
    """Implementation of plan_charging_route; flat_override bypasses the
    elevation model with a fixed Wh/mile rate (tests and what-if analysis)."""
    if not DEFAULT_SAFETY_BUFFER_SOC <= current_soc <= 100:
        return {"error": f"current_soc must be between {DEFAULT_SAFETY_BUFFER_SOC} and 100 "
                         f"(got {current_soc}). Ask the driver for the actual battery level."}
    segments = []
    notes = []
    start = origin
    soc = float(current_soc)
    total_charge_minutes = 0.0
    # Set while parked at a charger whose charge target isn't known yet (it
    # depends on the *next* leg): {"arrival_soc", "max_kw"}; the segment to
    # patch is always segments[-1].
    pending_charge = None

    def finalize_pending_charge(next_leg_soc_needed: float) -> float:
        """Sizes the charge at the stop we're parked at: 80% when that covers
        the next leg (+buffer +margin), stretched up to 95% when needed. A
        charge target never exceeds MAX_CHARGE_TARGET_SOC; if the car arrives
        already at/above the target (e.g., left the origin near 100% and the
        charger is close), the stop becomes a pass-through with no charging."""
        nonlocal total_charge_minutes, pending_charge
        arrival = pending_charge["arrival_soc"]
        required = next_leg_soc_needed + DEFAULT_SAFETY_BUFFER_SOC + CHARGE_MARGIN_SOC
        target = max(DEFAULT_CHARGE_TARGET_SOC,
                     min(MAX_CHARGE_TARGET_SOC, math.ceil(required)))
        segment = segments[-1]
        if arrival >= target:
            # Departure equals arrival: SOC state may sit above 95, but we
            # never *charge* past the cap.
            segment["action"] = f"No charging needed (continue at {int(round(arrival))}%)"
            segment["charge_time_minutes"] = 0.0
            pending_charge = None
            return arrival
        minutes = estimate_charge_time_minutes(arrival, target, pending_charge["max_kw"])
        segment["action"] = f"Charge to {target}% (~{round(minutes)} min)"
        segment["charge_time_minutes"] = round(minutes, 1)
        total_charge_minutes += minutes
        pending_charge = None
        return float(target)

    for _ in range(MAX_CHARGING_STOPS + 1):
        route = maps_client.compute_route(start, destination)
        if "error" in route:
            return {"error": route["error"]}

        profile, avg_rate, soc_needed, fallback_note = _leg_energy(route, flat_override)
        if fallback_note and fallback_note not in notes:
            notes.append(fallback_note)

        # Departure ceiling: at a charger we may charge up to 95% (or keep an
        # even higher arrival SOC without charging); at the origin we have
        # what we have.
        if pending_charge:
            max_departure = max(float(MAX_CHARGE_TARGET_SOC), pending_charge["arrival_soc"])
        else:
            max_departure = soc

        if max_departure - soc_needed >= DEFAULT_SAFETY_BUFFER_SOC:
            if pending_charge:
                soc = finalize_pending_charge(soc_needed)
            segments.append({
                "start": start,
                "end": destination,
                "distance_miles": round(route["distance_miles"], 1),
                "duration_minutes": round(route["duration_minutes"], 1),
                "departure_soc": int(round(soc)),
                "arrival_soc": int(round(soc - soc_needed)),
                "action": "Arrive at destination",
                "avg_consumption_wh_per_mile": round(avg_rate, 1),
            })
            plan = {
                "directly_reachable": len(segments) == 1,
                "total_distance_miles": round(sum(s["distance_miles"] for s in segments), 1),
                "total_duration_minutes": round(sum(s["duration_minutes"] for s in segments), 1),
                "total_charge_time_minutes": (round(total_charge_minutes, 1)
                                              if total_charge_minutes else None),
                "segments": segments,
                "notes": notes or None,
            }
            return ChargingPlan(**plan).model_dump()

        stop = _select_charging_stop(profile, max_departure, start, flat_override)
        if stop is None:
            return {"error": f"No working DC fast charger "
                             f"(≥{FALLBACK_MIN_CHARGER_POWER_KW:.0f} kW) is reachable along the "
                             f"route from '{start}' even at a {int(max_departure)}% departure. "
                             f"Charge to a higher SOC before departing, or plan a different route."}

        if pending_charge:
            soc = finalize_pending_charge(stop["soc_needed"])

        charger = stop["charger"]
        if charger.get("max_kw") and charger["max_kw"] < MIN_CHARGER_POWER_KW:
            notes.append(f"{charger['name']} is a slower charger "
                         f"({charger['max_kw']:.0f} kW) — no ≥{MIN_CHARGER_POWER_KW:.0f} kW "
                         f"station was reachable on this stretch.")
        arrival_soc = soc - stop["soc_needed"]
        segments.append({
            "start": start,
            "end": f"{charger['name']} ({charger['address']})",
            "distance_miles": round(stop["distance_miles"], 1),
            "duration_minutes": round(stop["duration_minutes"], 1),
            "departure_soc": int(round(soc)),
            "arrival_soc": int(round(arrival_soc)),
            "action": "Charge",  # patched by finalize_pending_charge next iteration
            "avg_consumption_wh_per_mile": round(stop["avg_rate"], 1),
            "charger_power_kw": charger.get("max_kw"),
            "charger_amenities": charger.get("amenities") or None,
        })
        pending_charge = {"arrival_soc": arrival_soc, "max_kw": charger.get("max_kw")}
        start = f"{charger['lat']},{charger['lng']}"
        soc = arrival_soc

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
