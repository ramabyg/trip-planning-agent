# 04 — Orchestrator Spec

## Purpose

Specifies the behavior of the conversational **Orchestrator Agent** (the Root Agent). The Orchestrator is the single user-facing entry point of the trip planner. It grounds each turn with trip context (dates, lodging, group splits) and orchestrates sub-agents to resolve charging, range, park alerts, weather, and dining, combining their responses into a single, cohesive itinerary.

## Scope

- Maintains conversational history in a chat session.
- Exposes tools to retrieve static trip context and upload planned itineraries.
- Registers sub-agents to handle specialized logistics:
  - Invokes `charging_planner` in **Task Mode** via the `charging_planner` task tool
    (ADK names the delegation tool after the sub-agent).
  - Invokes `park_logistics` in **Agent-as-a-Tool Mode** via its wrapped tool.
- Handles user intent routing, sub-agent invocation, and result aggregation.
- Synchronizes final plans by saving markdown itineraries to Google Cloud Storage (GCS).

## Agent Configuration (ADK)

- **Name**: `root_agent`
- **Model**: `gemini-3.5-flash`
- **Sub-agents**:
  - `charging_planner` (registered as a task sub-agent; model `gemini-3.1-pro-preview`)
- **Tools**:
  - `AgentTool(park_logistics)` (wrapped sub-agent; model `gemini-3.5-flash`)
  - `tools.get_trip_context`
  - `tools.save_and_upload_trip_plan`
  - Maps MCP toolset scoped to `compute_routes`, `search_places`, `lookup_weather`
    (routing for the gas cars, food/POI lookups, weather)

## Inputs

- `user_message`: The text message sent by the user.
- `current_location`: (Optional) User's current location. Defaults to the scheduled starting base for the active day if not specified.
- `current_soc`: User's current battery SOC (percentage, 10–100). **Never assumed**:
  if the user hasn't stated it in this or an earlier message, the Orchestrator must
  ask for it before delegating to the charging planner (see `tools.plan_charging_route`,
  which also rejects out-of-range values).
- `current_date`: (Optional) The date within the road trip range (2026-07-18 to
  2026-07-25). The Orchestrator grounds whichever date the question concerns via
  `get_trip_context(date=...)`; there is no hardcoded default date.

## Intent Routing & Execution Flow

1. **Context Grounding (Mandatory First Step)**:
   - For *every* user query, the Orchestrator calls `get_trip_context()` to identify:
     - The day of the trip (1 to 8).
     - The start/end lodgings and addresses.
     - Group composition and split status (specifically the July 23–25 split between West Glacier KOA and Kalispell).

2. **Intent Parsing & Sub-agent Delegation**:
   - **Charging/Routing**: If the query involves driving range, battery state, routing, or charging locations:
     - Call the `charging_planner` tool passing `origin`, `destination`, and `current_soc`.
   - **Park Alerts/Weather**: If the query asks about road status, trail closures, hikes, or weather forecasts:
     - Call the `park_logistics` tool passing the relevant `park_name`.
   - **Food/Restaurants**: If the query asks for dining options:
     - Call Maps MCP `search_places` using a location-based query.
   - **Cloud Sync**: If the user requests to "save", "sync", or "upload" the plan:
     - Compile the active day's plan and call `save_and_upload_trip_plan`.

3. **Aggregation & Synthesis**:
   - Merge the outputs from any invoked sub-agents into a single, unified response.
   - Inject context-grounded warnings, such as reminding the user of the July 23 split:
     > *Note: Family 1 is at West Glacier KOA, while Family 2/Family 3 are at Kalispell.*
   - If a plan was saved to GCS, display the returned signed URL link as: `[Sync Complete! View shareable cloud itinerary here](url)`.

## Output Schema

The Orchestrator returns a structured, user-friendly Markdown response containing:
1. **Trip Context Header**: Date, base locations, and active travelers.
2. **Detailed Plan Sections**:
   - Driving & Charging Segments (re-formatted from the `charging_planner`'s structured JSON).
   - Park alerts, closures, and weather forecast (taken from the `park_logistics` tool response).
   - Dining or scenic stops.
3. **Important Alerts**: Road closures, safety issues, or group splits.
4. **Cloud Sync Link**: The GCS signed URL if sync was requested.
