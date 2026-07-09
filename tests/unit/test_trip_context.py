"""Trip-context helpers: date grounding against specs/01-trip-context.md."""
import datetime

import pytest

import tools

D = datetime.date


class TestTripDayIndex:
    def test_first_day(self):
        assert tools.trip_day_index(D(2026, 7, 18)) == 1

    def test_last_day(self):
        assert tools.trip_day_index(D(2026, 7, 25)) == 8

    def test_middle_day(self):
        assert tools.trip_day_index(D(2026, 7, 21)) == 4

    @pytest.mark.parametrize("date", [D(2026, 7, 17), D(2026, 7, 26), D(2025, 7, 20)])
    def test_out_of_range_raises(self, date):
        with pytest.raises(ValueError):
            tools.trip_day_index(date)


class TestPreferences:
    def test_get_trip_context_returns_preferences(self):
        result = tools.get_trip_context("2026-07-21")
        prefs = result["preferences"]
        assert prefs, "preferences must flow through get_trip_context"
        assert any("hike" in rule.lower() for rule in prefs["daily"])
        assert any("lunch" in rule.lower() for rule in prefs["daily"])
        assert set(prefs["must_see"]) == {"grand_teton", "yellowstone", "glacier"}
        assert all(prefs["must_see"][park] for park in prefs["must_see"])


class TestCurrentBase:
    def test_shared_night_in_driggs(self):
        bases = tools.current_base(D(2026, 7, 19))
        assert len(bases) == 1
        assert "Driggs" in bases[0]["location"]

    def test_split_night_returns_both_lodgings(self):
        bases = tools.current_base(D(2026, 7, 23))
        assert len(bases) == 2
        descriptions = " ".join(str(b) for b in bases)
        assert "West Glacier" in descriptions
        assert "Kalispell" in descriptions

    def test_overnight_drive_home(self):
        bases = tools.current_base(D(2026, 7, 25))
        assert len(bases) == 1
        assert bases[0]["type"] == "none"


class TestIsGroupTogether:
    @pytest.mark.parametrize("day,expected", [
        (18, True), (19, True), (20, True), (21, True), (22, True),
        (23, False), (24, False), (25, False),
    ])
    def test_split_schedule(self, day, expected):
        assert tools.is_group_together(D(2026, 7, day)) is expected


class TestGetTripContext:
    def test_valid_date_returns_grounded_context(self):
        result = tools.get_trip_context("2026-07-21")
        assert result["trip_day_index"] == 4
        assert result["is_group_together"] is True
        assert len(result["current_base"]) == 1
        assert "KOA" in result["current_base"][0]["name"]
        assert result["trip"] is not None
        assert result["accommodations"]

    def test_invalid_date_format(self):
        result = tools.get_trip_context("not-a-date")
        assert "error" in result

    def test_date_outside_trip_range_warns(self):
        result = tools.get_trip_context("2026-08-01")
        assert "warning" in result
        assert "trip_day_index" not in result
        # Raw data is still returned so the agent can explain the trip range.
        assert result["accommodations"]

    def test_missing_spec_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr(tools, "SPEC_PATH", str(tmp_path / "missing.md"))
        result = tools.get_trip_context("2026-07-21")
        assert "error" in result

    def test_spec_without_yaml_block(self, monkeypatch, tmp_path):
        bad_spec = tmp_path / "01-trip-context.md"
        bad_spec.write_text("# Spec\nNo yaml here.\n", encoding="utf-8")
        monkeypatch.setattr(tools, "SPEC_PATH", str(bad_spec))
        result = tools.get_trip_context("2026-07-21")
        assert "error" in result
