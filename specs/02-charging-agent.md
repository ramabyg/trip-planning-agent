# 02 — Charging Agent Spec

## Purpose

Specifies the behavior of the **Charging Planner Sub-agent**. This sub-agent runs in **Task Mode** (`mode="task"`) and is responsible for calculating route segments, estimating battery consumption for the 2023 Tesla Model Y Long Range with an **elevation-aware energy model**, and selecting optimal DC fast-charging stops (Tesla Superchargers **and** CCS networks such as EVgo, Electrify America, and ChargePoint).

## Scope

- Operates as a task-driven sub-agent invoked by the root Orchestrator.
- Estimates battery state of charge (SOC) for drive segments using per-chunk, elevation-adjusted consumption.
- Queries the Google Routes API for segment distance, duration, and route geometry, and the Google Elevation API for terrain along the route.
- Queries Google Places API (New) for DC fast chargers along the route, filtered by connector type and charging speed, with real-time availability where networks report it.
- Iteratively plans charging stops with **adaptive charge targets (80% default, up to 95% when a leg demands it)** to construct a multi-segment route if the destination is out of range.
- Estimates charging time per stop from a piecewise Model Y charging curve.
- Returns a structured output conforming to the Pydantic schema below via the `finish_task` tool.

## Vehicle & Battery Specifications

- **Model**: 2023 Tesla Model Y Long Range (AWD), CCS Combo 1 adapter on board — can use any CCS DC fast charger in addition to Tesla Superchargers.
- **Battery Capacity**: 75 kWh usable.
- **Peak DC charge rate**: 250 kW (V3 Supercharger); CCS stations are used at `min(station kW, 250)`.
- **Safety Buffer**: Minimum 10% SOC (~26 miles remaining range) at any point, especially on arrival at chargers or destinations.

### Energy / consumption model (elevation-adaptive)

Consumption is computed **per ~5-mile chunk** of the route polyline, not as one flat rate for the trip:

```
wh_per_mile(chunk) = 280
                     + (ascent_m × 7.0 − descent_m × 2.8) / chunk_miles
clamped to [180, 550]
```

- **Base rate**: 280 Wh/mile (highway speeds, climate control, ~2,300 kg loaded).
- **Climb cost**: 7.0 Wh per meter of ascent (m·g·Δh at ~2,300 kg, ÷ 0.9 drivetrain efficiency).
- **Regen credit**: 2.8 Wh per meter of descent — deliberately conservative (**40% recovery**, though ~60% is realistic) so range estimates err on the safe side.
- Elevations come from the Google Elevation API sampled along the route polyline (≤512 samples per routed leg, ≈ one sample per 0.5 mile on the longest legs).
- **Fallback**: if elevation data is unavailable, use a flat 300 Wh/mile and record a warning in the plan's `notes`.

Leg energy = Σ chunk energies; reachability and the "max range point" for charger search walk the polyline accumulating **energy**, so terrain shortens usable range exactly where the terrain is.

The legacy flat 280/320 Wh/mile choice (made by the LLM) is **removed**: the tool computes consumption deterministically from route geometry.

### Charging target (adaptive)

- **Default target**: 80% — fast portion of the charging curve (~20–25 min at a 250 kW station).
- **Stretch target**: up to **95%** when the next hop's requirement (energy + 10% buffer + 5% margin) exceeds what 80% provides. `target = max(80, min(95, ceil(required_departure_soc)))`.
- Charging above 95% is never planned (too slow, battery-health cost).
- **Charge-time estimate** per stop, piecewise Model Y LR curve capped by station power `P = min(station_max_kw, 250)`:
  - 10→55%: average 170 kW × (P/250), never above P
  - 55→80%: average 95 kW, never above P
  - 80→95%: average 45 kW, never above P
  - `charge_time_minutes = Σ band_energy_kwh / effective_band_rate × 60`

## Charger Search & Selection

Chargers are found via Places API (New) `searchText` with:

- `includedType: "electric_vehicle_charging_station"`
- `evOptions.connectorTypes: [EV_CONNECTOR_TYPE_CCS_COMBO_1, EV_CONNECTOR_TYPE_TESLA]`
- `evOptions.minimumChargingRateKw: 100` — **primary tier**; slow stops waste trip time.
  - **Fallback tier**: if no ≥100 kW charger is reachable on a hop, retry at ≥50 kW and record a warning in `notes` (a slow charge beats a stranded car on sparse MT/WY stretches).
- Field mask includes `places.evChargeOptions` → per-connector `maxChargeRateKw`, `count`, `availableCount`, `outOfServiceCount`, `availabilityLastUpdateTime`.

**Working-charger verification**: real-time availability comes from `evChargeOptions` (networks like EVgo, Electrify America, and ChargePoint feed Google live status). Candidates whose availability is *known* and shows zero usable connectors are dropped. Candidates with *unknown* availability (many rural stations) are kept but ranked below live-confirmed ones. *PlugShare was evaluated and rejected: it has no public API (business partnerships only) and scraping violates its ToS.*

**No isolated stops**: each short-listed candidate gets a Places Nearby amenity check (~250 m radius: restaurant, cafe, convenience store, supermarket, gas station, shopping mall). Stops with shops/restrooms nearby are preferred; amenity names are surfaced in the plan.

**Candidate ranking** (deterministic tuple):
1. live-availability confirmed (desc)
2. has nearby amenities (desc)
3. detour distance from route (asc)
4. max charge rate kW (desc)

The search samples the route polyline at energy-budget fractions (0.95, 0.8, 0.65, 0.5, 0.35, 0.2) of the maximum reachable point, de-duplicates candidates by location, and tries the top 5.

## Agent Configuration (ADK)

- **Name**: `charging_planner`
- **Mode**: `task`
- **Output Schema**: `schemas.ChargingPlan` (enforced by ADK, not by prompt convention)
- **Tools**:
  - `tools.plan_charging_route` (the *only* tool — see implementation note below)
- **System Instruction**: Call `plan_charging_route` once, then return its result
  unchanged via the auto-injected `finish_task` tool. The tool handles terrain,
  charger selection, charge targets, and all range math deterministically; the
  LLM never chooses a consumption rate and never does range math.

> **Implementation note (2026-07, v2)**: The algorithm below is implemented as
> deterministic Python in `tools.plan_charging_route` (routing via Routes API v2,
> terrain via Elevation API, charger + amenity search via Places API (New), all
> through `maps_client.py`), not as LLM reasoning steps. Identical inputs
> therefore always produce the identical plan; the LLM only selects inputs and
> narrates the structured result. Covered by
> `tests/unit/test_charging_route_planner.py` and `tests/unit/test_energy_model.py`.

## Inputs (Task Arguments)

The sub-agent accepts the following inputs when invoked via the orchestrator's `charging_planner` task tool (ADK names the delegation tool after the sub-agent):

- `origin`: Starting location (address, coordinates, or Place ID).
- `destination`: Ending location (address, coordinates, or Place ID).
- `current_soc`: State of charge at departure (percentage, integer 10–100).
- `safety_buffer`: Optional override (defaults to 10%).

## Decision Logic / Algorithm

1. **Route & terrain**:
   - Compute the driving route (distance, duration, polyline).
   - Sample elevations along the polyline; build the per-chunk energy profile (see energy model above).

2. **Direct Route Check**:
   - `energy_needed_kwh = Σ chunk energies`; `soc_needed = energy_needed_kwh / 75 × 100`.
   - `arrival_soc = current_soc − soc_needed`.
   - If `arrival_soc ≥ safety_buffer`, the destination is reachable directly: emit a single segment and finish.

3. **Charging Search** (when not directly reachable):
   - Walk the energy profile to find the farthest polyline point reachable with the buffer intact (the *energy-budget point*).
   - Search for fast chargers near sample points at fractions of that budget (see Charger Search & Selection); rank and pick the best feasible candidate (arrival SOC ≥ buffer on the actual routed leg to the charger).
   - Determine the **charge target** at that stop from the *next* hop's requirement (adaptive 80→95 rule), estimate charge time, and continue planning from the charger.
   - Repeat until the destination is reachable with the buffer intact. Hard cap: **20 stops** (runaway guard, not a planning constraint).
   - If no charger is reachable even assuming a 95% departure (after the 50 kW fallback search), return an error advising a higher departure SOC or different route.

## Output Schema (Pydantic Model)

The sub-agent must call `finish_task` with a JSON payload matching this schema:

```python
from pydantic import BaseModel, Field

class RouteSegment(BaseModel):
    start: str
    end: str                                   # charger or final destination
    distance_miles: float
    duration_minutes: float                    # driving only
    departure_soc: int                         # 10-100
    arrival_soc: int                           # 10-100
    action: str                                # e.g. "Charge to 90% (~34 min)" or "Arrive at destination"
    avg_consumption_wh_per_mile: float | None  # elevation-adjusted average for the segment
    charge_time_minutes: float | None          # None for the final (arrival) segment
    charger_power_kw: float | None             # station max kW, None for arrival segment
    charger_amenities: list[str] | None        # nearby shops/food, None for arrival segment

class ChargingPlan(BaseModel):
    directly_reachable: bool
    total_distance_miles: float
    total_duration_minutes: float              # driving only (sum of segments)
    total_charge_time_minutes: float | None    # sum of charge stops (None/0 when no stops)
    segments: list[RouteSegment]
    notes: list[str] | None                    # warnings: elevation fallback, sub-100kW stop, etc.
```

All v2 fields are additive and optional so existing consumers keep working.

## Edge Cases / Rules

- **Cold Weather**: The elevation model covers terrain; cold-weather and traffic/speed adjustments are explicitly **future work** (July trip — see Out of Scope in the v2 plan).
- **Destination Charging**: If the destination is a campground (KOA West Yellowstone, KOA West Glacier) with RV hookups, note that the vehicle can charge overnight (NEMA 14-50 50A hookup charges to 100% in ~8 hours). Therefore, arrival SOC at campgrounds can be as low as 10%, but arrival SOC at hotels/Airbnbs without chargers should be high enough to reach the nearest fast charger the next morning.
- **Sparse corridors**: the 50 kW fallback tier plus the 95% stretch target exist specifically for MT/WY stretches where ≥100 kW chargers may be >160 mi apart.
