"""Public-repo privacy: address overrides overlay and flow-log masking."""
import pytest

import flow_log
import tools


class TestTripContextOverrides:
    def test_overrides_merge_by_id(self, tmp_path, monkeypatch):
        overlay = tmp_path / "overrides.yaml"
        overlay.write_text(
            "accommodations:\n"
            "  airbnb-driggs:\n"
            '    address: "42 Test Lane, Driggs, ID 83422"\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(tools, "OVERRIDES_PATH", str(overlay))
        context = tools._parse_context()
        by_id = {a.get("id"): a for a in context["accommodations"]}
        assert by_id["airbnb-driggs"]["address"] == "42 Test Lane, Driggs, ID 83422"
        # Untouched entries keep their committed (city-level) values.
        assert "West Yellowstone" in by_id["koa-westgate"]["address"]

    def test_missing_overrides_file_keeps_committed_values(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tools, "OVERRIDES_PATH", str(tmp_path / "absent.yaml"))
        context = tools._parse_context()
        by_id = {a.get("id"): a for a in context["accommodations"]}
        # The committed spec must never contain a street number for this entry.
        assert by_id["airbnb-driggs"]["address"] == "Driggs, ID 83422"

    def test_every_accommodation_has_a_stable_id(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tools, "OVERRIDES_PATH", str(tmp_path / "absent.yaml"))
        context = tools._parse_context()
        assert all(a.get("id") for a in context["accommodations"])


class TestFlowLogMasking:
    def _capture(self, monkeypatch):
        lines = []
        monkeypatch.setattr(flow_log, "_emit", lines.append)
        return lines

    def test_signed_url_result_is_masked(self, monkeypatch):
        from types import SimpleNamespace as NS
        lines = self._capture(monkeypatch)
        flow_log.after_tool_callback(
            tool=NS(name="save_and_upload_trip_plan"), args={},
            tool_context=NS(agent_name="root_agent"),
            tool_response="https://storage.googleapis.com/bucket/f.md?X-Goog-Signature=abc123",
        )
        assert len(lines) == 1
        assert "masked" in lines[0]
        assert "X-Goog-Signature" not in lines[0]
        assert "abc123" not in lines[0]

    def test_other_tools_still_logged(self, monkeypatch):
        from types import SimpleNamespace as NS
        lines = self._capture(monkeypatch)
        flow_log.after_tool_callback(
            tool=NS(name="get_trip_context"), args={},
            tool_context=NS(agent_name="root_agent"),
            tool_response={"trip_day_index": 3},
        )
        assert len(lines) == 1
        assert "trip_day_index" in lines[0]
