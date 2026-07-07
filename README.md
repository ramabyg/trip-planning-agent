# Yellowstone Trip Agent

A conversational, agentic trip-planning assistant for a July 2026 road trip from
Santa Clara, CA to Yellowstone / Grand Teton / Glacier National Parks.

Built as a learning project for Agentic AI concepts: **Multi-Agent Systems (ADK)**, **MCP servers**,
**Task Delegation/Agent-as-a-Tool patterns**, and **Spec-Driven Development (SDD)**.

## Why this project

The trip has a useful mix of:
- **Fixed, unchangeable facts**: accommodation bookings, travel dates, group composition.
- **Dynamic, replanning-worthy variables**: traffic, weather, Tesla Supercharger
  availability, NPS road/trail status, restaurant options en route.

That split is what makes "dynamic replanning" a meaningful agent capability here,
rather than a toy demo.

## Approach: Spec-Driven Development (SDD)

Every agent/integration starts as a spec in `specs/` before any code is
written. Specs are living documents, version-controlled via git, and updated
as understanding evolves. See `specs/00-overview.md` for the spec index and
conventions.

## Project structure

```
yellowstone-trip-agent/
├── specs/              # SDD specs — written before implementation
├── mcp-servers/         # MCP server configs / thin wrapper servers
├── docs/
│   └── architecture.md  # System architecture (agents, data flow, tool boundaries)
├── agent.py            # Orchestrator and sub-agent definitions
├── schemas.py          # Pydantic output contracts (ChargingPlan)
├── tools.py            # Shared tools & MCP wrappers
├── maps_client.py      # Direct Routes/Places REST access for deterministic planning
├── main.py             # FastAPI entry point / ADK app setup
├── tests/              # Unit (offline) + integration (live, keys-gated) suites
├── scripts/            # run_checks.py — pre-commit verification
└── README.md
```

## Testing

See `specs/05-testing.md` for the full strategy.

```bash
pip install -r requirements-dev.txt

pytest                              # offline unit tests (default)
pytest -m integration               # live API tests (needs MAPS_API_KEY / NPS_API_KEY in .env)
pytest -m eval                      # agent-level evals (model-in-the-loop; needs GEMINI_API_KEY)
python scripts/run_checks.py        # commit gate: import sanity + unit tests
python scripts/run_checks.py --all  # everything except agent evals
```

Enable the pre-commit hook once per clone so failing checks block commits:

```bash
git config core.hooksPath .githooks
```

## Status

✅ Phase 1a: conversational agent with a task-mode charging planner
(deterministic routing/SOC math, structured `ChargingPlan` output), scoped MCP
toolsets, mock-data disclosure, and an offline + live test suite with a
pre-commit verification gate.

✅ Phase 1b: agent-level evaluation (`pytest -m eval`) — ADK `AgentEvaluator`
eval sets covering context grounding, charging-planner delegation, and the
simulated-data disclosure rule, graded by exact tool trajectories plus an
LLM-as-judge response metric. See `specs/05-testing.md`.

## Phase 1 scope (current)

Conversational agent only — user asks "what should we do next / where should
we charge / what's the road status" and the agent answers using live data via
MCP + skill-encoded domain logic. No background/proactive triggers yet (that's
a planned Phase 2).
