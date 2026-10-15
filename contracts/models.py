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


class KPIResponse(KPISet):
    synthetic: Literal[True] = True


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


class CopilotRequest(Contract):
    query: str = Field(min_length=1, max_length=2000)


class RunRequest(Contract):
    scenario: str = "S1"
    seed: int = 42
    days: int = Field(default=1, ge=1, le=70)
    cv_mode: Literal["oracle", "simulated"] = "simulated"


class RunResponse(Contract):
    scenario: str
    seed: int
    days: int
    synthetic: Literal[True] = True
    output_dir: str
    manifest: dict[str, object]


class WhatIfRequest(Contract):
    action: ControlCommand
    horizon_min: int = Field(default=60, ge=1, le=240)
    scenario: str | None = None
    seed: int = 42


class WhatIfResponse(Contract):
    baseline: KPISet
    projected: KPISet
    delta: dict[str, float]
    seed: int
    synthetic: Literal[True] = True


class ForecastPoint(Contract):
    timestamp: datetime
    predicted_kw: float = Field(ge=0)


class ForecastResponse(Contract):
    method: str
    points: list[ForecastPoint]
    synthetic: Literal[True] = True


class AnomalyEvent(Contract):
    timestamp: datetime
    main_kw: float = Field(ge=0)
    threshold_kw: float = Field(gt=0)
    score: float = Field(ge=0)
    detector: str = "threshold_alert"


class AnomalyResponse(Contract):
    events: list[AnomalyEvent]
    synthetic: Literal[True] = True


class RecommendationDecision(Contract):
    recommendation_id: str
    status: Literal["approved", "rejected", "scheduled"]
    scheduled_for: datetime | None = None
    message: str


class RecommendationScheduleRequest(Contract):
    scheduled_for: datetime


class ReportResponse(Contract):
    markdown: str
    synthetic: Literal[True] = True
