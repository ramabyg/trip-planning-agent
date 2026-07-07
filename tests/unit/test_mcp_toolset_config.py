"""Maps MCP toolset factory: connection and scoping config (no network)."""
from google.adk.tools.mcp_tool import McpToolset

import tools


def test_toolset_connection_configuration(monkeypatch):
    monkeypatch.setenv("MAPS_API_KEY", "test-key-123")

    toolset = tools.get_maps_mcp_toolset(tool_filter=["compute_routes"])

    assert isinstance(toolset, McpToolset)
    connection = toolset._connection_params
    assert connection.url == tools.MAPS_MCP_URL
    assert connection.headers["X-Goog-Api-Key"] == "test-key-123"
    assert toolset.tool_filter == ["compute_routes"]


def test_toolset_without_filter_exposes_everything(monkeypatch):
    monkeypatch.setenv("MAPS_API_KEY", "test-key-123")
    toolset = tools.get_maps_mcp_toolset()
    assert toolset.tool_filter is None


def test_missing_api_key_falls_back_to_placeholder():
    toolset = tools.get_maps_mcp_toolset()
    assert toolset._connection_params.headers["X-Goog-Api-Key"] == "no_api_found"
