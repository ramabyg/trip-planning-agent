# Implementation Plan

Phased delivery plan for the Yellowstone Trip Agent. Specs in `specs/` define
*behavior*; this document tracks *sequencing and status*. (Earlier versions of
this plan lived only in working notes — it is now versioned here.)

## Phase 1 — Conversational agent (current)

Scope: chat-based agent that re-plans the remainder of the current day against
live conditions, on top of fixed trip facts. No proactive triggers, no mobile
UI, no multi-user sync (see `specs/00-overview.md` non-goals).

### Phase 1a — Core agent + deterministic planning + test gate ✅ (2026-07)

- Root orchestrator (`agent.py`) grounded on fixed trip context
  (`specs/01-trip-context.md`, parsed by `tools.get_trip_context`).
- Charging planner sub-agent in Task Mode with a structured `ChargingPlan`
  output; all routing/SOC math is deterministic Python
  (`tools.plan_charging_route` + `maps_client.py`), never LLM arithmetic
  (`specs/02-charging-agent.md`).
- Park logistics sub-agent (Agent-as-a-Tool) with NPS alerts (live or mock,
  always tagged with `source`) and weather (`specs/03-park-logistics.md`).
- Scoped Maps MCP toolsets per agent; mock-data disclosure rule.
- Test suite per `specs/05-testing.md`: offline unit tests (fake road
  network), keys-gated live integration tests, and the
  `scripts/run_checks.py` pre-commit gate wired via `.githooks/`.

### Phase 1b — Agent-level evaluation ✅ (2026-07)

- Eval sets in ADK `EvalSet` schema under `tests/eval/`:
  - `grounding/` — fixed-fact questions; exact `get_trip_context` tool
    trajectory + LLM-judged response.
  - `delegation/` — charging-planner delegation and the Many Glacier
    road-status question (which also verifies the simulated-data disclosure
    rule); LLM-judged response only.
- Runs on demand via `pytest -m eval` (pytest wrapper around ADK's
  `AgentEvaluator`, exposed through the `eval_entry.py` shim). Excluded from
  the commit gate — model-in-the-loop and costs money.
- Baseline: all 4 cases passed live on 2026-07-06.

## Phase 2 — Proactive agent + cloud deployment (planned, not started)

Candidate scope, to be spec'd before implementation (SDD):

- Background/proactive triggers (watch location/time and push alerts) —
  explicitly out of Phase 1 scope.
- Cloud deployment of the FastAPI/ADK app (load/perf testing deferred to this
  phase per `specs/05-testing.md`).
- Grow the eval sets from the Phase 1b baseline as regressions appear.
