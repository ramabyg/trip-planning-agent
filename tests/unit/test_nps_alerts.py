"""NPS alerts tool: live/mock source tagging and fallbacks."""
import io
import json
import urllib.request

import pytest

import tools


def test_no_api_key_returns_tagged_mock_alerts():
    alerts = tools.get_nps_alerts("Yellowstone")
    assert len(alerts) == 2
    assert all(alert["source"] == "mock" for alert in alerts)


@pytest.mark.parametrize("park,expected_title_fragment", [
    ("Yellowstone", "Mudslide"),
    ("Grand Teton", "Signal Mountain"),
    ("Glacier", "Highline"),
])
def test_mock_alerts_per_park(park, expected_title_fragment):
    alerts = tools.get_nps_alerts(park)
    assert any(expected_title_fragment in alert["title"] for alert in alerts)


def test_park_name_matching_is_fuzzy():
    alerts = tools.get_nps_alerts("  glacier national park ")
    assert all(alert["source"] == "mock" for alert in alerts)
    assert len(alerts) == 2


def test_unknown_park():
    alerts = tools.get_nps_alerts("Yosemite")
    assert len(alerts) == 1
    assert alerts[0]["title"] == "Unknown Park"
    assert alerts[0]["source"] == "mock"


class FakeResponse:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_live_api_alerts_tagged_live(monkeypatch):
    monkeypatch.setenv("NPS_API_KEY", "real-key")
    payload = {"data": [{"title": "Real Closure", "description": "Live alert", "category": "Danger"}]}
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["api_key"] = req.headers.get("X-api-key")
        return FakeResponse(payload)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    alerts = tools.get_nps_alerts("Yellowstone")

    assert alerts == [{"title": "Real Closure", "description": "Live alert",
                       "category": "Danger", "source": "live"}]
    assert "parkCode=yell" in captured["url"]
    assert captured["api_key"] == "real-key"


def test_api_failure_falls_back_to_mock(monkeypatch):
    monkeypatch.setenv("NPS_API_KEY", "real-key")

    def failing_urlopen(req, timeout=None):
        raise OSError("network down")

    monkeypatch.setattr(urllib.request, "urlopen", failing_urlopen)
    alerts = tools.get_nps_alerts("Glacier")

    assert len(alerts) == 2
    assert all(alert["source"] == "mock" for alert in alerts)
