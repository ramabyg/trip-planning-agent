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
| Unit (offline) | `tests/unit/` | nothing | trip-context helpers, Tesla range math, elevation-adaptive energy model + charging curve, deterministic charging planner (fake road network: terrain, availability, amenities, charge-target caps), NPS alert tagging/fallbacks, `ChargingPlan` schema contract, agent wiring (incl. flow-log callbacks and the ADK streaming patch), MCP toolset config, plan save/upload (mocked GCS) |
| Integration (live) | `tests/integration/` | `MAPS_API_KEY` / `NPS_API_KEY` in `.env` | Maps MCP transport + auth + expected tool surface, Routes/Places REST plausibility, live NPS alerts tagged `source: live` |
| Agent-level eval (Phase 1b) | `tests/eval/` | `GEMINI_API_KEY` + `MAPS_API_KEY` in `.env`, `google-adk[eval]` extras | end-to-end behavior on the canonical questions from `specs/00-overview.md`: context grounding, sub-agent delegation, mock-data disclosure |

Run them:

```bash
pytest                          # unit only (default; integration + eval deselected)
pytest -m integration           # live suite only
pytest -m eval                  # agent-level evals (model-in-the-loop, costs money)
python scripts/run_checks.py        # commit gate: imports + unit
python scripts/run_checks.py --all  # everything except agent evals
```

## The fake road network

`tests/conftest.py` provides `FakeMaps`: locations and DC fast chargers placed
at mile markers along a straight line, with routes computed by the same
haversine the production geometry helpers use. Chargers carry the v2 planner's
attributes (max kW, live `available_count`, nearby amenities) and terrain is
flat by default with `set_hill(start, end, peak_m)` to build elevation
profiles. Flat terrain reproduces the 280 Wh/mile base rate exactly (e.g.,
190 miles from 90% arrives at exactly 19%), so planner tests assert real
numbers, not ranges; hills, availability, amenity ranking, and charge-target
edge cases each get their own deterministic scenarios.

## Agent-level evaluation (Phase 1b)

`tests/eval/test_agent_eval.py` drives the real orchestrator (live Gemini +
Google Maps) over eval sets in ADK's `EvalSet` schema, via a pytest wrapper
around ADK's `AgentEvaluator` — the same engine behind `adk eval`. The raw
`adk eval` CLI is not used because it requires an `__init__.py`-based agent
package layout; this repo keeps `agent.py` flat at the root, exposed to the
evaluator through the `eval_entry.py` shim.

Two eval sets, each with its own `test_config.json` criteria:

| Eval set | Cases | Criteria | Rationale |
|---|---|---|---|
| `tests/eval/grounding/` | lodging + group split questions for Jul 20 / Jul 23 | `tool_trajectory_avg_score: 1.0`, `final_response_match_v2: 0.7` | fixed facts: the exact `get_trip_context(date=...)` call and the answer are both deterministic |
| `tests/eval/delegation/` | Tesla charging question (Driggs → West Yellowstone), Many Glacier road status | `final_response_match_v2: 0.7` | routes through sub-agents are path-dependent, so no trajectory pinning; the LLM judge grades the final answer against a reference. The park case also verifies the simulated-data disclosure rule (no `NPS_API_KEY` → mock alerts). |

`final_response_match_v2` is an LLM-as-judge metric. The judge model is
**pinned to `gemini-3.5-flash`** via `judge_model_options` in each
`test_config.json` — ADK 2.4's built-in default (`gemini-2.5-flash`) 404s for
newer API keys ("no longer available to new users"), and pinning also keeps
the judge independent of the agent models in `agent.py` (currently
`gemini-3.5-flash` across all three agents). Chosen over ROUGE-based
`response_match_score` because
answers legitimately vary in phrasing and include live route numbers.

Cost policy: each case is one full agent run plus judge calls (`num_runs=1`).
Evals run **on demand only** (`pytest -m eval`) — never in the commit gate,
never in `run_checks.py --all`.

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
- google-adk 2.3/2.4 dispatches task delegations from partial (unpersisted)
  streaming events, orphaning the synthesized function response and poisoning
  the session ("No function call event found for function responses ids").
  Worked around in `adk_patches.py`; guarded by
  `tests/unit/test_agent_wiring.py::test_adk_task_streaming_patch_applied`
  (2026-07).

## Non-goals

- No UI tests for the static frontend (Phase 1 scope).
- No load/performance testing until the Phase 2 cloud deployment.
