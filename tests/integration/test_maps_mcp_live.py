"""Live Maps MCP connectivity: transport, auth, and expected tool surface."""
import os

import pytest

import tools

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("MAPS_API_KEY"), reason="MAPS_API_KEY not set"),
]


async def test_mcp_server_exposes_expected_tools():
    toolset = tools.get_maps_mcp_toolset()
    try:
        mcp_tools = await toolset.get_tools()
        tool_names = {t.name for t in mcp_tools}
        assert {"compute_routes", "search_places", "lookup_weather"} <= tool_names, (
            f"Maps MCP tool surface changed: {sorted(tool_names)}")
    finally:
        await toolset.close()


async def test_tool_filter_restricts_surface():
    toolset = tools.get_maps_mcp_toolset(tool_filter=["lookup_weather"])
    try:
        mcp_tools = await toolset.get_tools()
        assert {t.name for t in mcp_tools} == {"lookup_weather"}
    finally:
        await toolset.close()
