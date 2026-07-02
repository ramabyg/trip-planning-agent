# 02 — Charging Agent Spec

## Purpose

Specifies the behavior of the **Charging Planner Sub-agent**. This sub-agent runs in **Task Mode** (`mode="task"`) and is responsible for calculating route segments, estimating battery consumption for the 2023 Tesla Model Y Long Range, and selecting optimal Tesla Supercharging locations.

## Scope

- Operates as a task-driven sub-agent invoked by the root Orchestrator.
- Estimates battery state of charge (SOC) for drive segments.
- Queries Google Maps MCP `compute_routes` for segment distance, duration, and route geometry.
- Queries Maps MCP `search_places` to locate Tesla Superchargers along the route.
- Recursively plans charging stops to construct a multi-segment route if the destination is out of range.
- Returns a structured output conforming to the Pydantic schema below via the `finish_task` tool.

## Vehicle & Battery Specifications

- **Model**: 2023 Tesla Model Y Long Range (AWD)
- **Battery Capacity**: 75 kWh usable.
- **Realistic Road Trip Range**: 260 miles (factoring in highway speeds, elevation changes, and climate control).
- **Consumption Rate**: ~280 Wh/mile (~3.57 miles/kWh).
- **Safety Buffer**: Minimum 10% SOC (~26 miles remaining range) at any point, especially on arrival at chargers or destinations.
- **Charging Target**: Standard road trip charge is up to 80% (which takes ~20–25 minutes at a V3 250 kW Supercharger). Charging above 80% is slower and only recommended if a segment exceeds 180 miles without chargers.

## Agent Configuration (ADK)

- **Name**: `charging_planner`
- **Mode**: `task`
- **Tools**:
  - `tools.calculate_tesla_segments`
  - `tools.get_maps_mcp_toolset()` (specifically using `compute_routes` and `search_places`)
- **System Instruction**: Guide the LLM to recursively check reachability, search for Superchargers, split the route, and call the auto-injected `finish_task` tool with the structured Pydantic schema once routing is complete.

## Inputs (Task Arguments)

The sub-agent accepts the following inputs when invoked via the orchestrator's `request_task_charging_planner` tool:

- `origin`: Starting location (address, coordinates, or Place ID).
- `destination`: Ending location (address, coordinates, or Place ID).
- `current_soc`: State of charge at departure (percentage, integer 10–100).
- `safety_buffer`: Optional override (defaults to 10%).

## Decision Logic / Algorithm

1. **Direct Route Check**:
   - Query Maps MCP `compute_routes` to get the distance (in miles) and duration between `origin` and `destination`.
   - Calculate energy required: `energy_needed_kwh = distance * 0.280`.
   - Calculate SOC required: `soc_needed = (energy_needed_kwh / 75) * 100`.
   - Projected arrival SOC: `arrival_soc = current_soc - soc_needed`.
   - If `arrival_soc >= safety_buffer`, the destination is reachable directly. Wrap in a single segment and exit via `finish_task`.

2. **Charging Search**:
   - If `arrival_soc < safety_buffer`, intermediate charging is required.
   - Calculate maximum drivable distance before hitting buffer:
     `max_distance = ((current_soc - safety_buffer) / 100) * 75 / 0.280` (miles).
   - Query Maps MCP `search_places` using the text query "Tesla Supercharger" centered along the route near the `max_distance` mark.
   - Choose a Supercharger location.
   - Calculate route from `origin` to the selected Supercharger.
   - Recalculate arrival SOC at the Supercharger.
   - Assume charging to 80% SOC at the Supercharger.
   - Repeat the process recursively from the Supercharger to the final `destination` until the destination is reachable with at least the safety buffer.

## Output Schema (Pydantic Model)

The sub-agent must call `finish_task` with a JSON payload matching this schema:

```python
from pydantic import BaseModel, Field

class RouteSegment(BaseModel):
    start: str = Field(description="Starting point for this segment")
    end: str = Field(description="Ending point for this segment (charger or final destination)")
    distance_miles: float = Field(description="Segment distance in miles")
    duration_minutes: float = Field(description="Segment duration in minutes")
    departure_soc: int = Field(description="State of charge at departure (10-100)")
    arrival_soc: int = Field(description="State of charge on arrival (10-100)")
    action: str = Field(description="Action at the end of the segment, e.g., 'Charge to 80%' or 'Arrive at destination'")

class ChargingPlan(BaseModel):
    directly_reachable: bool = Field(description="True if the destination can be reached without charging stops")
    total_distance_miles: float = Field(description="Sum of all segment distances")
    total_duration_minutes: float = Field(description="Sum of all segment durations")
    segments: list[RouteSegment] = Field(description="List of ordered drive segments")
```

## Edge Cases / Rules

- **Elevation & Cold Weather**: If traveling over mountain passes or in cold weather (e.g. Glacier NP high altitudes), increase the consumption rate to 320 Wh/mile (reduces range to ~230 miles).
- **Destination Charging**: If the destination is a campground (KOA West Yellowstone, KOA West Glacier) with RV hookups, note that the vehicle can charge overnight (NEMA 14-50 50A hookup charges to 100% in ~8 hours). Therefore, arrival SOC at campgrounds can be as low as 10%, but arrival SOC at hotels/Airbnbs without chargers should be high enough to reach the nearest Supercharger the next morning.
