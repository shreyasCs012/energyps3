"""Stable boundary schemas shared across the simulator, API, and frontend."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class EquipmentState(StrEnum):
    OFF = "OFF"
    STANDBY = "STANDBY"
    WARMUP = "WARMUP"
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    MAINTENANCE = "MAINTENANCE"
    FAULT = "FAULT"


class ControlAction(StrEnum):
    STANDBY = "STANDBY"
    PRE_WARM = "PRE_WARM"
    LIGHTS_OFF = "LIGHTS_OFF"
    HVAC_SETBACK = "HVAC_SETBACK"
    DEFER_JOB = "DEFER_JOB"


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TelemetryPoint(Contract):
    timestamp: datetime
    equipment_id: str = Field(min_length=1)
    power_kw: float = Field(ge=0)
    state: EquipmentState | None = None
    source: str = "synthetic"


class ControlCommand(Contract):
    command_id: str = Field(min_length=1)
    issued_at: datetime
    equipment_id: str = Field(min_length=1)
    action: ControlAction
    duration_min: int | None = Field(default=None, ge=1)
    rationale: str


class KPISet(Contract):
    energy_kwh: float = Field(ge=0)
    peak_15min_kw: float = Field(ge=0)
    cost_inr: float = Field(ge=0)
    co2_kg: float = Field(ge=0)
    idle_waste_kwh: float = Field(ge=0)
    restarts: int = Field(ge=0)
    late_jobs: int = Field(ge=0)
    comfort_violation_min: int = Field(ge=0)


class KPIComparison(Contract):
    predicted: KPISet
    realized: KPISet
    absolute_error: dict[str, float]
