"""Local workarounds for google-adk bugs. Import before building agents.

PATCH 1: task delegation must ignore partial (streaming) events.
----------------------------------------------------------------
Bug (present in google-adk 2.3.0 and 2.4.0): with SSE token streaming
(`RunConfig(streaming_mode=SSE)`, i.e. the `adk web` dev UI), a chat
coordinator's task-mode delegation crashes every turn with:

    ValueError: No function call event found for function responses ids: {...}

Mechanism: `workflow/_llm_agent_wrapper.run_llm_agent_as_node` extracts the
task-delegation function call from the FIRST event that carries it — in
streaming mode that is a *partial* event, which is never persisted to the
session. The wrapper then dispatches the sub-agent and `break`s out of the
LLM stream, so the final consolidated event (the one that would persist the
function call) is never produced. The synthesized function *response* IS
persisted, leaving an orphan; the next content rebuild
(`flows/llm_flows/contents.py::_rearrange_events_for_latest_function_response`)
raises the ValueError above and the session is stuck.

Fix: skip partial events when sniffing for task-delegation FCs. The final
non-partial event carries the same FC, is persisted upstream, and pairs
correctly with the synthesized FR. Non-streaming behavior is unchanged
(events are never partial there).

Verified by scratchpad `repro_poisoned_session.py`: on 2.4.0 without this
patch a single streamed charging prompt crashes; with it, both the streamed
run and the abort-then-reprompt recovery pass. Remove once fixed upstream
(google/adk-python — see issues #3531/#4159 for the error family).
"""
from google.adk.workflow import _llm_agent_wrapper as _wrapper

_original_extract = _wrapper._extract_task_delegation_fcs


def _extract_task_delegation_fcs_skip_partials(event, tools_dict):
    if getattr(event, "partial", None):
        return []
    return _original_extract(event, tools_dict)


def apply() -> None:
    _wrapper._extract_task_delegation_fcs = _extract_task_delegation_fcs_skip_partials


apply()
