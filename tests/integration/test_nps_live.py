"""Live NPS alerts API."""
import os

import pytest

import tools

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("NPS_API_KEY"), reason="NPS_API_KEY not set"),
]


def test_yellowstone_alerts_are_live():
    alerts = tools.get_nps_alerts("Yellowstone")
    assert isinstance(alerts, list)
    assert all(alert["source"] == "live" for alert in alerts), (
        "live key present but alerts fell back to mock — check API/key")
    for alert in alerts:
        assert alert["title"]
