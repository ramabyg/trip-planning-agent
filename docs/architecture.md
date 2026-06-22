# Architecture

Status: draft — Phase 1 (conversational agent only)

## 1. High-level shape

```
                      ┌─────────────────────────┐
                      │   Orchestrator Agent     │
                      │  (conversational, stateful│
                      │   per session)            │
                      └───────────┬───────────────┘
                                  │
        ┌─────────────┬──────────┼──────────────┬─────────────┐
        ▼             ▼          ▼              ▼             ▼
  trip-context   charging-   park-logistics  food/restaurant  (future
     skill       planner        skill           lookup        skills)
   (static data)  skill      (NPS, weather)   (MCP: Places)
                (MCP: maps,
                 charger APIs)
```

The orchestrator is a single conversational agent. It does not run
continuously — it answers in response to user turns. Each turn:

1. Reads fixed trip context (via `trip-context` skill) to know where we are
   in the trip (date, current/next accommodation, group split status).
2. Determines which dynamic skill(s) are relevant to the question.
3. Calls the relevant skill(s), which call MCP servers for live data.
4. Synthesizes a single answer, scoped to "today" or the specific question
   — never silently re-planning the whole 8-day trip.

## 2. Agent / Skill boundary

**Skills** = domain knowledge + decision rules + how to call the right
tools. They are mostly prompt/markdown + light logic, not full agents.

**Orchestrator** = the only thing holding conversational state and making
the call on which skill(s) to invoke. In Phase 1 there is exactly one
orchestrator — no subagent-to-subagent delegation yet. This keeps the
debugging surface small while still exercising the Skills + MCP concepts.

| Component | Type | Responsibility |
|---|---|---|
| trip-context | Skill (static) | Source of truth for bookings/dates/group |
| charging-planner | Skill + MCP | Tesla range/charging logic given location + battery |
| park-logistics | Skill + MCP | NPS road/trail status, weather-aware hike suggestions |
| food-lookup | Skill + MCP | Restaurant search en route (Google Places) |
| Orchestrator | Agent | Routes queries, merges results, keeps "today" state |

## 3. MCP servers (Phase 1 candidates)

| MCP server | Purpose | Notes |
|---|---|---|
| Maps/Routing (e.g. Google Maps) | Drive time, traffic, route polylines | Needed by charging + food skills |
| Weather (NWS/NOAA or similar) | Current + short-term forecast | Needed by park-logistics |
| NPS data | Road/trail status, alerts | NPS publishes a public API; need to verify current alert granularity |
| Tesla | Live SOC/location (optional) | Community MCP servers exist; could also start with manual "current battery %" input from the user rather than live telemetry, to reduce auth complexity in Phase 1 |
| Google Places | Restaurant search en route | Already used in our other tooling patterns |

**Phase 1 simplification**: Tesla live telemetry is the highest-effort,
highest-auth-complexity integration. Recommend starting with the user
manually reporting battery % and location in chat, and only build the
Tesla MCP integration once the rest of the pipeline (charging-planner
skill logic, MCP plumbing pattern) is proven out with the other servers.

## 4. Data flow example

**User**: "We're leaving Gardiner now, 70% battery, heading toward
Glacier today — where should we charge and is there anything worth
stopping for?"

1. Orchestrator → `trip-context` skill: confirms today is a transition day
   (Gardiner → West Glacier KOA), checks group-split note (not yet in
   effect until Jul 23).
2. Orchestrator → `charging-planner` skill: given start location, 70%
   battery, destination → calls Maps MCP for route, evaluates whether a
   Supercharger stop is needed en route or arrival SOC is sufficient.
3. Orchestrator → `park-logistics` skill: checks if route passes near any
   open trails/viewpoints worth a stop, using NPS + Weather MCP.
4. Orchestrator merges: one answer — charging stop (if needed) + 1-2
   worthwhile stops — scoped to today only.

## 5. SDD workflow tie-in

Each row in the component table above gets its own spec before code:
- `specs/01-trip-context.md` ✅ drafted
- `specs/02-charging-agent.md` — next
- `specs/03-park-logistics.md` — next
- `specs/04-orchestrator.md` — next

Architecture changes (e.g. adding a subagent layer in Phase 2) should be
reflected here and cross-referenced from the relevant spec.

## 6. Open questions

- Which Maps/routing provider — Google Maps API vs. another option?
  (Affects MCP server choice and Supercharger-aware routing quality.)
- NPS API — confirm current alert/closure data granularity before relying
  on it for trail decisions.
- Tesla integration approach — community MCP vs. manual input vs. Tesla's
  own API (requires OAuth app registration) — needs a decision before
  `02-charging-agent.md` can be finalized.
- Where does the orchestrator run day-to-day during the actual trip —
  Claude Code on a laptop, Claude.ai chat, or something else? Affects how
  "current location/time" gets into context each turn.
