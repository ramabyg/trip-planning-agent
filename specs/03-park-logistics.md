# 03 — Park Logistics Spec

## Purpose

Specifies the behavior of the **Park Logistics Sub-agent**. This sub-agent is wrapped using the **Agent as a Tool** pattern (`AgentTool(park_logistics_agent)`), allowing the root Orchestrator to invoke it to check weather forecasts, query NPS road/trail status alerts, and receive natural language activity recommendations.

## Scope

- Operates as a conversational helper sub-agent invoked as a tool by the root Orchestrator.
- Retrieves active park closures and alerts from the NPS Alerts API or falls back to simulated realistic alerts.
- Retrieves weather conditions from Google Maps MCP `lookup_weather`.
- Suggests alternative trails/scenic routes in case of active park alerts or adverse weather conditions.
- Returns a rich, natural language summary detailing weather, alerts, and recommendations back to the Orchestrator.

## Agent Configuration (ADK)

- **Name**: `park_logistics`
- **Mode**: `chat` (or `single_turn` since it executes in a single query-response turn from the Orchestrator)
- **Tools**:
  - `tools.get_nps_alerts`
  - `tools.get_maps_mcp_toolset()` (specifically using the `lookup_weather` tool)
- **System Instruction**: Guide the LLM to map park names to their NPS codes, look up weather, get alerts, identify closures, and formulate a clear list of hike recommendations and detours.

## Inputs (Tool Arguments)

When the Orchestrator calls the `park_logistics` agent via `AgentTool`, it provides:

- `park_name`: Name of the park ("Yellowstone", "Grand Teton", "Glacier").

## Decision Logic / Rules

1. **Park Code Mapping**:
   - "Yellowstone" -> `yell`
   - "Grand Teton" -> `grte`
   - "Glacier" -> `glac`

2. **NPS Alerts Retrieval**:
   - Request alerts from `https://developer.nps.gov/api/v1/alerts?parkCode=[code]` using the API key.
   - If no key is provided, or the API call fails, load the local mock alert dataset:
     - *Yellowstone Mock Alerts*: Road closure between Tower Junction and Canyon Village due to mudslides; Yellowstone Canyon Rim trail restricted due to construction.
     - *Glacier Mock Alerts*: Going-to-the-Sun Road is open, but Many Glacier road is restricted to timed-entry permits; Highline Trail is temporarily closed due to grizzly bear activity.
     - *Grand Teton Mock Alerts*: Jenny Lake ferry operating normally; Signal Mountain road closed for repair.

3. **Weather Lookup**:
   - Call Maps MCP `lookup_weather` at coordinates corresponding to the center of each park:
     - Yellowstone: `44.4280, -110.5885`
     - Grand Teton: `43.7904, -110.6818`
     - Glacier: `48.7596, -113.7870`

4. **Recommendation Logic**:
   - If a primary attraction/road is closed (e.g. Going-to-the-Sun Road in Glacier or Canyon road in Yellowstone):
     - Filter and display the closure.
     - Recommend backups (e.g. "Take US-2 around the southern boundary of Glacier instead" or "Visit the Norris Geyser Basin instead of Canyon Village").
   - If heavy rain, snow, or thunderstorms are forecast:
     - Suggest indoor/scenic drive alternatives (e.g. Visitor centers, historic lodges like Old Faithful Inn or Lake McDonald Lodge).

## Output Format

The agent returns a formatted text output to the orchestrator containing:
1. **Weather Summary**: Current conditions and short-term forecast for the park center.
2. **Active Alerts**: List of warnings, closures, and cautions.
3. **Alternative Recommendations**: Actionable backup plans if primary sites are closed or weather is poor.
