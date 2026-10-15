from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from contracts.models import ControlAction, ControlCommand, EquipmentState, KPISet, TelemetryPoint


def test_telemetry_contract_accepts_valid_point() -> None:
    point = TelemetryPoint(
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        equipment_id="CNC-01",
        power_kw=1.25,
        state=EquipmentState.IDLE,
    )
    assert point.power_kw == 1.25
    assert point.source == "synthetic"


def test_contract_rejects_negative_power_and_unknown_fields() -> None:
    values = {
        "timestamp": datetime(2026, 1, 1, tzinfo=UTC),
        "equipment_id": "CNC-01",
        "power_kw": -0.1,
        "surprise": True,
    }
    with pytest.raises(ValidationError):
        TelemetryPoint(**values)


def test_command_requires_positive_duration() -> None:
    with pytest.raises(ValidationError):
        ControlCommand(
            command_id="cmd-1",
            issued_at=datetime(2026, 1, 1, tzinfo=UTC),
            equipment_id="CNC-01",
            action=ControlAction.STANDBY,
            duration_min=0,
            rationale="idle gap",
        )


def test_kpis_reject_negative_values() -> None:
    with pytest.raises(ValidationError):
        KPISet(
            energy_kwh=-1,
            peak_15min_kw=0,
            cost_inr=0,
            co2_kg=0,
            idle_waste_kwh=0,
            restarts=0,
            late_jobs=0,
            comfort_violation_min=0,
        )
