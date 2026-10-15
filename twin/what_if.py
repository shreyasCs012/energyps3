"""Common-random-number what-if comparison for one proposed action."""

from contracts.models import ControlCommand
from twin.model import TwinSnapshot, WhatIfResult
from twin.simulate import simulate


def what_if(
    state: TwinSnapshot,
    schedule,
    action: ControlCommand,
    horizon_min: int,
    scenario: dict | None = None,
    seed: int = 0,
) -> WhatIfResult:
    """Compare do-nothing and one action with identical noise draws."""
    baseline = simulate(state, schedule, [], horizon_min, scenario, seed)
    projected = simulate(state, schedule, [action], horizon_min, scenario, seed)
    delta = {
        name: float(getattr(baseline.kpis, name) - getattr(projected.kpis, name))
        for name in type(baseline.kpis).model_fields
    }
    return WhatIfResult(baseline, projected, delta, seed)
