"""Sub-agent communication contracts: how the agents are wired together.

No LLM calls — these inspect the constructed agent objects so a config
regression (wrong mode, missing schema, lost tool) fails fast in CI.
"""
from google.adk.tools import AgentTool
from google.adk.tools.mcp_tool import McpToolset

import agent
import schemas
import tools


class TestChargingPlanner:
    def test_runs_in_task_mode(self):
        assert agent.charging_planner.mode == "task"

    def test_structured_output_contract(self):
        assert agent.charging_planner.output_schema is schemas.ChargingPlan

    def test_only_tool_is_the_deterministic_planner(self):
        # Task mode auto-injects FinishTaskTool; the only tool WE give it is
        # the deterministic planner (no MCP toolset, no range-math tools).
        provided = [t for t in agent.charging_planner.tools if callable(t)]
        assert provided == [tools.plan_charging_route]
        injected = [type(t).__name__ for t in agent.charging_planner.tools if not callable(t)]
        assert injected == ["FinishTaskTool"]

    def test_registered_as_task_sub_agent_of_root(self):
        assert agent.charging_planner in agent.root_agent.sub_agents

    def test_description_present_for_delegation(self):
        assert agent.charging_planner.description


class TestParkLogistics:
    def test_exposed_to_root_as_agent_tool(self):
        wrapped = [t.agent.name for t in agent.root_agent.tools if isinstance(t, AgentTool)]
        assert "park_logistics" in wrapped

    def test_has_nps_alerts_tool(self):
        assert tools.get_nps_alerts in agent.park_logistics.tools

    def test_maps_toolset_scoped_to_weather(self):
        toolsets = [t for t in agent.park_logistics.tools if isinstance(t, McpToolset)]
        assert len(toolsets) == 1
        assert toolsets[0].tool_filter == ["lookup_weather"]

    def test_instruction_requires_mock_disclosure(self):
        assert "mock" in agent.park_logistics.instruction.lower()

    def test_description_present_for_delegation(self):
        assert agent.park_logistics.description


class TestRootAgent:
    def test_has_context_and_sync_tools(self):
        assert tools.get_trip_context in agent.root_agent.tools
        assert tools.save_and_upload_trip_plan in agent.root_agent.tools

    def test_maps_toolset_scoped(self):
        toolsets = [t for t in agent.root_agent.tools if isinstance(t, McpToolset)]
        assert len(toolsets) == 1
        assert set(toolsets[0].tool_filter) == {"compute_routes", "search_places", "lookup_weather"}


def test_root_honors_planning_preferences():
    # Day plans must bake in the family's fixed preferences from
    # get_trip_context (specs/01-trip-context.md `preferences` section).
    instruction = agent.root_agent.instruction
    assert "ONE moderate" in instruction
    assert "grab-and-go" in instruction
    assert "must_see" in instruction


def test_root_grounds_on_prompting_family():
    # Deployed UI tags every session with "Prompting family: Family N"; the
    # root agent must use it (and ask when it's absent) and must never send
    # the gas-car families to the charging planner.
    instruction = agent.root_agent.instruction
    assert "Prompting family" in instruction
    assert "ASK who is prompting" in instruction
    assert "NEVER need the charging planner" in instruction


def test_flow_log_callbacks_attached_to_every_agent():
    # The real-time terminal flow log must observe every agent's hops.
    import flow_log
    for llm_agent in (agent.root_agent, agent.charging_planner, agent.park_logistics):
        assert llm_agent.before_agent_callback is flow_log.before_agent_callback
        assert llm_agent.after_agent_callback is flow_log.after_agent_callback
        assert llm_agent.before_model_callback is flow_log.before_model_callback
        assert llm_agent.before_tool_callback is flow_log.before_tool_callback
        assert llm_agent.after_tool_callback is flow_log.after_tool_callback


def test_adk_task_streaming_patch_applied():
    # adk_patches works around a google-adk 2.3/2.4 bug where task delegation
    # under SSE streaming dispatches from a partial (unpersisted) event and
    # poisons the session ("No function call event found for function
    # responses ids"). agent.py must keep importing it.
    import adk_patches
    from google.adk.workflow import _llm_agent_wrapper
    assert (_llm_agent_wrapper._extract_task_delegation_fcs
            is adk_patches._extract_task_delegation_fcs_skip_partials)

    from google.adk.events import Event
    from google.genai import types as genai
    partial_fc_event = Event(
        author="root_agent",
        invocation_id="inv",
        partial=True,
        content=genai.Content(role="model", parts=[genai.Part(
            function_call=genai.FunctionCall(id="x", name="charging_planner", args={}))]),
    )
    assert _llm_agent_wrapper._extract_task_delegation_fcs(partial_fc_event, {}) == []


def test_low_temperature_on_every_agent():
    for llm_agent in (agent.root_agent, agent.charging_planner, agent.park_logistics):
        config = llm_agent.generate_content_config
        assert config is not None, f"{llm_agent.name} has no generate_content_config"
        assert config.temperature is not None and config.temperature <= 0.2, (
            f"{llm_agent.name} temperature must be pinned low for consistent planning")
