"""Agent-level evaluation (Phase 1b, specs/05-testing.md).

Model-in-the-loop: every case drives the real orchestrator against live Gemini
and Google Maps, then grades the result (LLM-as-judge for responses, exact
match for pinned tool trajectories). Costs money and is non-deterministic by
nature — run on demand with `pytest -m eval`, never as part of the commit gate.
"""
import os

import pytest
from google.adk.evaluation.agent_evaluator import AgentEvaluator

pytestmark = pytest.mark.eval

EVAL_ROOT = os.path.dirname(os.path.abspath(__file__))


async def test_grounding_eval_set():
    """Fixed-fact questions: exact get_trip_context trajectory + judged response."""
    await AgentEvaluator.evaluate(
        agent_module="eval_entry",
        eval_dataset_file_path_or_dir=os.path.join(EVAL_ROOT, "grounding"),
        num_runs=1,
    )


async def test_delegation_eval_set():
    """Charging delegation and park-logistics mock disclosure, judged response only."""
    await AgentEvaluator.evaluate(
        agent_module="eval_entry",
        eval_dataset_file_path_or_dir=os.path.join(EVAL_ROOT, "delegation"),
        num_runs=1,
    )
