"""Structured output contracts shared by agents and tools.

Source of truth: specs/02-charging-agent.md (Output Schema section).
"""
from pydantic import BaseModel, Field


class RouteSegment(BaseModel):
    start: str = Field(description="Starting point for this segment")
    end: str = Field(description="Ending point for this segment (charger or final destination)")
    distance_miles: float = Field(description="Segment distance in miles")
    duration_minutes: float = Field(description="Segment driving duration in minutes (excludes charging)")
    departure_soc: int = Field(description="State of charge at departure (10-100)")
    arrival_soc: int = Field(description="State of charge on arrival (10-100)")
    action: str = Field(description="Action at the end of the segment, e.g., 'Charge to 90% (~34 min)' or 'Arrive at destination'")
    avg_consumption_wh_per_mile: float | None = Field(
        default=None, description="Elevation-adjusted average consumption for this segment")
    charge_time_minutes: float | None = Field(
        default=None, description="Estimated charging time at the end of this segment (None when arriving at the destination)")
    charger_power_kw: float | None = Field(
        default=None, description="Max charge rate of the station at the end of this segment")
    charger_amenities: list[str] | None = Field(
        default=None, description="Shops/food within walking distance of the charging stop")


class ChargingPlan(BaseModel):
    directly_reachable: bool = Field(description="True if the destination can be reached without charging stops")
    total_distance_miles: float = Field(description="Sum of all segment distances")
    total_duration_minutes: float = Field(description="Sum of all segment driving durations (excludes charging)")
    total_charge_time_minutes: float | None = Field(
        default=None, description="Total estimated time spent charging (None when no stops)")
    segments: list[RouteSegment] = Field(description="List of ordered drive segments")
    notes: list[str] | None = Field(
        default=None, description="Warnings such as elevation-data fallback or a slower-than-100kW stop")
