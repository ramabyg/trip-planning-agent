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

    def test_group_overrides_merge_by_family_name(self, tmp_path, monkeypatch):
        overlay = tmp_path / "overrides.yaml"
        overlay.write_text(
            "group:\n"
            '  "Family 2":\n'
            '    flight_arrival: "UA1234 SFO->JAC 2026-07-18 11:05 MT"\n'
            '    members: "Test Names"\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(tools, "OVERRIDES_PATH", str(overlay))
        context = tools._parse_context()
        by_name = {g["name"]: g for g in context["trip"]["group"]}
        assert by_name["Family 2"]["flight_arrival"].startswith("UA1234")
        assert by_name["Family 2"]["members"] == "Test Names"
        # Untouched families keep committed values and gain nothing.
        assert "flight_arrival" not in by_name["Family 1"]

    def test_trip_overrides_shallow_merge_protects_group(self, tmp_path, monkeypatch):
        overlay = tmp_path / "overrides.yaml"
        overlay.write_text(
            "trip:\n"
            '  emergency_contact: "555-0100"\n'
            '  group: "must-not-clobber"\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(tools, "OVERRIDES_PATH", str(overlay))
        context = tools._parse_context()
        assert context["trip"]["emergency_contact"] == "555-0100"
        # `group` in the trip overlay is ignored — the list survives intact.
        assert isinstance(context["trip"]["group"], list)
        assert len(context["trip"]["group"]) == 3


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
