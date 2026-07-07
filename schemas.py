"""Structured output contracts shared by agents and tools.

Source of truth: specs/02-charging-agent.md (Output Schema section).
"""
from pydantic import BaseModel, Field


class RouteSegment(BaseModel):
    start: str = Field(description="Starting point for this segment")
    end: str = Field(description="Ending point for this segment (charger or final destination)")
    distance_miles: float = Field(description="Segment distance in miles")
    duration_minutes: float = Field(description="Segment duration in minutes")
    departure_soc: int = Field(description="State of charge at departure (10-100)")
    arrival_soc: int = Field(description="State of charge on arrival (10-100)")
    action: str = Field(description="Action at the end of the segment, e.g., 'Charge to 80%' or 'Arrive at destination'")


class ChargingPlan(BaseModel):
    directly_reachable: bool = Field(description="True if the destination can be reached without charging stops")
    total_distance_miles: float = Field(description="Sum of all segment distances")
    total_duration_minutes: float = Field(description="Sum of all segment durations")
    segments: list[RouteSegment] = Field(description="List of ordered drive segments")
