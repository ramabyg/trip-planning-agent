# 05 — Testing & Verification Spec

## Purpose

Defines the test strategy for the trip agent: what is verified at which layer,
what runs offline vs. against live APIs, and the verification gate that must
pass before any commit.

## Principles

1. **Deterministic logic gets deterministic tests.** Everything that can be
   computed in Python (range math, route splitting, date grounding) is tested
   exactly, offline, with no LLM in the loop.
2. **Agent wiring is a contract.** Sub-agent modes, output schemas, tool
   scoping, and temperature settings are asserted directly on the constructed
   agent objects — a config regression fails in seconds, not mid-trip.
3. **Live connectivity is verified separately.** Keys-gated integration tests
   prove the real Maps MCP / REST / NPS endpoints still work; they are skipped
   automatically when keys are absent so the offline suite never blocks.
4. **LLM behavior is evaluated, not unit-tested.** Model-in-the-loop checks are
   non-deterministic and cost money; they live in eval datasets run on demand
   (see "Agent-level evaluation" below), not in the commit gate.

## Test layers

| Layer | Location | Needs | Verifies |
|---|---|---|---|
| Unit (offline) | `tests/unit/` | nothing | trip-context helpers, Tesla range math, deterministic charging planner (fake road network), NPS alert tagging/fallbacks, `ChargingPlan` schema contract, agent wiring, MCP toolset config, plan save/upload (mocked GCS) |
| Integration (live) | `tests/integration/` | `MAPS_API_KEY` / `NPS_API_KEY` in `.env` | Maps MCP transport + auth + expected tool surface, Routes/Places REST plausibility, live NPS alerts tagged `source: live` |
| Agent-level eval | (planned, Phase 1b) | model access | end-to-end answer quality/consistency on the canonical questions from `specs/00-overview.md`, via `adk eval` |

Run them:

```bash
pytest                          # unit only (default; integration deselected)
pytest -m integration           # live suite only
python scripts/run_checks.py        # commit gate: imports + unit
python scripts/run_checks.py --all  # everything
```

## The fake road network

`tests/conftest.py` provides `FakeMaps`: locations and Superchargers placed at
mile markers along a straight line, with routes computed by the same haversine
the production geometry helpers use. This makes expected SOC values exact
(e.g., 190 miles from 90% at 280 Wh/mile arrives at exactly 19%), so planner
tests assert real numbers, not ranges.

## Commit gate

- `scripts/run_checks.py` — stage 1 imports every module (`schemas`,
  `maps_client`, `tools`, `agent`); stage 2 runs the offline unit suite.
  Non-zero exit on any failure.
- `.githooks/pre-commit` runs the script and blocks the commit on failure.
  Enable once per clone:

  ```bash
  git config core.hooksPath .githooks
  ```

Integration tests are **not** part of the gate (network flakiness must not
block commits); run them before deploys and after changing anything in
`maps_client.py` or `tools.get_maps_mcp_toolset`.

## Regressions this suite has already caught

- The Google Maps MCP endpoint rejects SSE connections (`405 Method Not
  Allowed`); it requires the streamable-HTTP transport. Caught by
  `tests/integration/test_maps_mcp_live.py`, fixed in
  `tools.get_maps_mcp_toolset` (2026-07).

## Non-goals

- No UI tests for the static frontend (Phase 1 scope).
- No load/performance testing until the Phase 2 cloud deployment.
