"""Twin-side state, calibrated parameters, and projection results."""

from dataclasses import dataclass, field
from datetime import datetime

from contracts.models import EquipmentState, KPISet


@dataclass
class MachineParameters:
    equipment_id: str
    p_run_kw: float
    p_idle_kw: float
    p_standby_kw: float
    warmup_min: int
    restart_kwh: float
    min_off_min: int
    min_on_min: int
    needs: tuple[str, ...] = ()
    submetered: bool = False


@dataclass
class TwinSnapshot:
    timestamp: datetime
    machine_states: dict[str, EquipmentState]
    machine_power_kw: dict[str, float]
    temperature_c: float = 24.0
    occupied: bool = False
    confidence: dict[str, float] = field(default_factory=dict)


@dataclass
class TwinResult:
    kpis: KPISet
    per_machine_kwh: dict[str, float]
    temperature_trace_c: list[float]
    state_trace: dict[str, list[str]]
    constraint_violations: list[str]
    seed: int


@dataclass
class WhatIfResult:
    baseline: TwinResult
    action: TwinResult
    delta: dict[str, float]
    seed: int
