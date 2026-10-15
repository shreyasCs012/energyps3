"""P2 naive idle shutdown: STANDBY after a fixed idle-time threshold."""

from pathlib import Path

import pandas as pd
import yaml

from contracts.models import ControlAction, ControlCommand, EquipmentState
from policies.models import PolicyDecision


def evaluate(
    estimates: pd.DataFrame,
    idle_minutes: int | None = None,
    standby_duration_min: int | None = None,
) -> PolicyDecision:
    """Create commands for machines currently idle for the threshold duration.

    This intentionally mirrors the naive Phase 2 baseline and does not check break-even,
    dependency, or warmup lead-time constraints; the optimizer adds those in Phase 5.
    """
    if idle_minutes is None or standby_duration_min is None:
        config = yaml.safe_load(Path("config/policies.yaml").read_text(encoding="utf-8"))
        idle_minutes = int(idle_minutes or config["rule_idle_shutdown"]["idle_minutes"])
        standby_duration_min = int(
            standby_duration_min or config["rule_idle_shutdown"]["standby_duration_min"]
        )
    if idle_minutes < 1 or standby_duration_min < 1:
        raise ValueError("idle and standby durations must be positive")
    required = {"timestamp", "equipment_id", "state"}
    if not required.issubset(estimates.columns):
        raise ValueError(f"estimates must contain {sorted(required)}")
    commands: list[ControlCommand] = []
    for equipment_id, group in estimates.sort_values("timestamp").groupby(
        "equipment_id", sort=True
    ):
        rows = list(group.itertuples())
        if not rows or rows[-1].state != EquipmentState.IDLE.value:
            continue
        run_length = 0
        for row in reversed(rows):
            if row.state != EquipmentState.IDLE.value:
                break
            run_length += 1
        if run_length < idle_minutes:
            continue
        timestamp = pd.Timestamp(rows[-1].timestamp).to_pydatetime()
        commands.append(
            ControlCommand(
                command_id=f"idle-{equipment_id}-{timestamp:%Y%m%d%H%M}",
                issued_at=timestamp,
                equipment_id=equipment_id,
                action=ControlAction.STANDBY,
                duration_min=standby_duration_min,
                rationale=f"Estimated IDLE state persisted for {run_length} minutes.",
            )
        )
    return PolicyDecision(commands=commands)
