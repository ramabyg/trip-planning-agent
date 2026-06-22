# Yellowstone Trip Agent

A conversational, agentic trip-planning assistant for a July 2026 road trip from
Santa Clara, CA to Yellowstone / Grand Teton / Glacier National Parks.

Built as a learning project for Agentic AI concepts: **Skills**, **MCP servers**,
**multi-agent orchestration**, and **Spec-Driven Development (SDD)**.

## Why this project

The trip has a useful mix of:
- **Fixed, unchangeable facts**: accommodation bookings, travel dates, group composition.
- **Dynamic, replanning-worthy variables**: traffic, weather, Tesla Supercharger
  availability, NPS road/trail status, restaurant options en route.

That split is what makes "dynamic replanning" a meaningful agent capability here,
rather than a toy demo.

## Approach: Spec-Driven Development (SDD)

Every agent/skill/integration starts as a spec in `specs/` before any code is
written. Specs are living documents, version-controlled via git, and updated
as understanding evolves. See `specs/00-overview.md` for the spec index and
conventions.

## Project structure

```
yellowstone-trip-agent/
├── specs/              # SDD specs — written before implementation
├── skills/             # Claude Skills (domain knowledge + procedures)
│   ├── trip-context/        # Fixed trip data: bookings, dates, constraints
│   ├── charging-planner/    # Tesla charging logic
│   └── park-logistics/      # NPS roads, trails, weather heuristics
├── mcp-servers/         # MCP server configs / thin wrapper servers
├── docs/
│   └── architecture.md  # System architecture (agents, data flow, tool boundaries)
└── README.md
```

## Status

🚧 Early architecture / spec phase. No implementation yet.

## Phase 1 scope (current)

Conversational agent only — user asks "what should we do next / where should
we charge / what's the road status" and the agent answers using live data via
MCP + skill-encoded domain logic. No background/proactive triggers yet (that's
a planned Phase 2).
