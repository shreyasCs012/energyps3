"""Stable boundary schemas shared across the simulator, API, and frontend."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

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
    setpoint_delta_c: float | None = Field(default=None, gt=0)


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


class RecommendationImpact(Contract):
    energy_kwh: float
    cost_inr: float
    co2_kg: float
    peak_kw: float
    late_jobs: float


class RecommendationInterval(Contract):
    p05: RecommendationImpact
    p95: RecommendationImpact


class RecommendationConstraint(Contract):
    rule: str = Field(min_length=1)
    passed: bool
    detail: str


class Recommendation(Contract):
    id: str = Field(min_length=1)
    ts: datetime
    equipment: str = Field(min_length=1)
    action: ControlAction
    action_parameters: dict[str, float | str] = Field(default_factory=dict)
    start: datetime
    duration_min: int = Field(ge=1)
    projected: RecommendationImpact
    interval: RecommendationInterval
    constraints: list[RecommendationConstraint]
    confidence: float = Field(ge=0, le=1)
    evidence: dict[str, object]
    revert_if: list[str]


class RecommendationPlan(Contract):
    mode: Literal["human", "auto"]
    recommendations: list[Recommendation]
    rejected: list[dict[str, object]]


class RecommendationExplanation(Contract):
    summary: str
    rationale: str
    impact: dict[str, str]
    constraints: list[str]
    caveats: list[str]


class CopilotResponse(Contract):
    tool: Literal["what_if", "get_kpis", "list_anomalies", "forecast"]
    answer: str
    result: dict[str, object]
