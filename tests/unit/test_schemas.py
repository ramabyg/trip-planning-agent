"""ChargingPlan output contract: what the charging sub-agent must return."""
import pytest
from pydantic import ValidationError

from schemas import ChargingPlan, RouteSegment

CANONICAL_SEGMENT = {
    "start": "Santa Clara, CA",
    "end": "Tesla Supercharger Elko (1900 Idaho St)",
    "distance_miles": 210.5,
    "duration_minutes": 195.0,
    "departure_soc": 100,
    "arrival_soc": 21,
    "action": "Charge to 80%",
}


def test_canonical_plan_validates():
    plan = ChargingPlan(
        directly_reachable=False,
        total_distance_miles=430.2,
        total_duration_minutes=400.0,
        segments=[
            CANONICAL_SEGMENT,
            {**CANONICAL_SEGMENT, "start": CANONICAL_SEGMENT["end"],
             "end": "Driggs, ID", "departure_soc": 80, "arrival_soc": 25,
             "action": "Arrive at destination"},
        ],
    )
    assert len(plan.segments) == 2
    assert plan.segments[0].departure_soc == 100


def test_missing_segments_rejected():
    with pytest.raises(ValidationError):
        ChargingPlan(directly_reachable=True, total_distance_miles=10.0,
                     total_duration_minutes=12.0)


def test_wrong_types_rejected():
    with pytest.raises(ValidationError):
        RouteSegment(**{**CANONICAL_SEGMENT, "departure_soc": "almost full"})


def test_missing_segment_field_rejected():
    incomplete = dict(CANONICAL_SEGMENT)
    del incomplete["arrival_soc"]
    with pytest.raises(ValidationError):
        RouteSegment(**incomplete)
