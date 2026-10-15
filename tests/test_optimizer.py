from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from contracts.models import ControlAction, ControlCommand, EquipmentState
from policies.optimizer import (
    _Candidate,
    _job_shift_candidate,
    break_even_minutes,
    check_constraints,
    optimize,
)
from twin.config import load_twin_config
from twin.model import TwinSnapshot


@pytest.fixture
def machine_setup():
    machines, _ = load_twin_config("config/facility.yaml")
    snapshot = TwinSnapshot(
        timestamp=datetime(2025, 1, 1, 8, tzinfo=UTC),
        machine_states={name: EquipmentState.IDLE for name in machines},
        machine_power_kw={name: machine.p_idle_kw for name, machine in machines.items()},
        temperature_c=24.0,
    )
    return machines, snapshot


def test_break_even_includes_restart_energy_and_minimum_off_time(machine_setup):
    machines, _ = machine_setup
    assert break_even_minutes(machines["CNC-01"]) == pytest.approx(60 * 0.6 / 1.8)
    assert break_even_minutes(machines["HP1"]) == pytest.approx(60 * 1.8 / 2.9)


def test_standby_rejected_when_a_consumer_needs_compressor(machine_setup):
    machines, snapshot = machine_setup
    snapshot.machine_states["CNC-02"] = EquipmentState.RUNNING
    schedule = pd.DataFrame(
        columns=["start_ts", "end_ts", "required_machines", "critical", "job_id"]
    )
    candidate = _Candidate("C2", ControlAction.STANDBY, pd.Timestamp(snapshot.timestamp), 60)
    checks = check_constraints(
        candidate, snapshot, schedule, machines, {name: 60 for name in machines}, 240, None
    )
    dependency = next(item for item in checks if item.rule == "compressor_dependency")
    assert not dependency.passed


def test_critical_job_cannot_be_deferred(machine_setup):
    machines, snapshot = machine_setup
    now = pd.Timestamp(snapshot.timestamp)
    schedule = pd.DataFrame(
        [
            {
                "job_id": "critical",
                "start_ts": now + pd.Timedelta(minutes=30),
                "end_ts": now + pd.Timedelta(minutes=60),
                "due_ts": now + pd.Timedelta(minutes=90),
                "required_machines": "CNC-01",
                "shiftable": True,
                "critical": True,
            }
        ]
    )
    candidate = _Candidate(
        "JOB:critical",
        ControlAction.DEFER_JOB,
        now + pd.Timedelta(minutes=45),
        30,
        job_id="critical",
    )
    checks = check_constraints(candidate, snapshot, schedule, machines, {}, 240, None)
    due = next(item for item in checks if item.rule == "job_release_due_critical")
    assert not due.passed


def test_standby_rejected_before_upcoming_critical_job(machine_setup):
    machines, snapshot = machine_setup
    now = pd.Timestamp(snapshot.timestamp)
    schedule = pd.DataFrame(
        [
            {
                "job_id": "critical-soon",
                "start_ts": now + pd.Timedelta(minutes=60),
                "end_ts": now + pd.Timedelta(minutes=90),
                "required_machines": "CNC-01",
                "critical": True,
            }
        ]
    )
    candidate = _Candidate("CNC-01", ControlAction.STANDBY, now, 60)
    checks = check_constraints(
        candidate, snapshot, schedule, machines, {name: 60 for name in machines}, 240, None
    )
    critical = next(item for item in checks if item.rule == "critical_job_protection")
    assert not critical.passed


def test_optimizer_emits_contract_valid_recommendations_and_is_repeatable(machine_setup, tmp_path):
    _, snapshot = machine_setup
    schedule = pd.DataFrame(
        columns=[
            "job_id",
            "start_ts",
            "end_ts",
            "due_ts",
            "required_machines",
            "shiftable",
            "critical",
        ]
    )
    config = tmp_path / "optimizer.yaml"
    config.write_text(
        "mode: human\nhorizon_minutes: 30\nensemble_seeds: 2\n"
        "max_concurrent_startups: 2\njob_shift_slot_minutes: 15\n"
        "peak_cap_kw: null\nco2_weight_inr_per_kg: 0.0\n"
        "late_job_penalty_inr: 10000\npeak_penalty_inr_per_kw: 0\n",
        encoding="utf-8",
    )
    first = optimize(snapshot, schedule, config_path=config)
    second = optimize(snapshot, schedule, config_path=config)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.mode == "human"
    assert all(all(check.passed for check in item.constraints) for item in first.recommendations)
    assert all(item.projected.cost_inr >= 0 for item in first.recommendations)


def test_auto_mode_is_explicit_and_invalid_mode_rejected(machine_setup, tmp_path):
    _, snapshot = machine_setup
    schedule = pd.DataFrame(columns=["job_id", "start_ts", "end_ts", "due_ts", "required_machines"])
    config = tmp_path / "optimizer.yaml"
    config.write_text("horizon_minutes: 15\nensemble_seeds: 1\n", encoding="utf-8")
    assert optimize(snapshot, schedule, mode="auto", config_path=config).mode == "auto"
    with pytest.raises(ValueError, match="mode"):
        optimize(snapshot, schedule, mode="automatic", config_path=config)


def test_constraint_checker_never_standbys_compressor_with_active_consumer(machine_setup):
    machines, base_snapshot = machine_setup
    schedule = pd.DataFrame(
        columns=["job_id", "start_ts", "end_ts", "required_machines", "critical"]
    )
    now = pd.Timestamp(base_snapshot.timestamp)
    candidate = _Candidate("C2", ControlAction.STANDBY, now, 60)
    rng = np.random.default_rng(2025)
    active_states = (EquipmentState.RUNNING, EquipmentState.WARMUP)
    for _ in range(200):
        active_machine = str(rng.choice(("CNC-02", "HP1")))
        active_state = active_states[int(rng.integers(0, len(active_states)))]
        snapshot = TwinSnapshot(
            timestamp=base_snapshot.timestamp,
            machine_states={
                **base_snapshot.machine_states,
                active_machine: active_state,
            },
            machine_power_kw=dict(base_snapshot.machine_power_kw),
            state_age_min={name: int(rng.integers(1, 1441)) for name in machines},
        )
        checks = check_constraints(
            candidate,
            snapshot,
            schedule,
            machines,
            snapshot.state_age_min,
            240,
            None,
        )
        dependency = next(item for item in checks if item.rule == "compressor_dependency")
        assert dependency.passed is False


def test_zone_light_command_targets_only_its_zone(machine_setup):
    machines, snapshot = machine_setup
    schedule = pd.DataFrame()
    cmd = ControlCommand(
        command_id="lights-z1",
        issued_at=snapshot.timestamp,
        equipment_id="LIGHTS:Z1",
        action=ControlAction.LIGHTS_OFF,
        duration_min=15,
        rationale="zone is idle",
    )
    from twin.simulate import simulate

    baseline = simulate(snapshot, schedule, [], 15, seed=5)
    projected = simulate(snapshot, schedule, [cmd], 15, seed=5)
    assert baseline.kpis.energy_kwh - projected.kpis.energy_kwh == pytest.approx(
        1.4 * 15 / 60, abs=0.005
    )


def test_job_shift_fallback_moves_flexible_work_into_a_cheaper_slot(machine_setup):
    machines, snapshot = machine_setup
    now = pd.Timestamp(snapshot.timestamp)
    schedule = pd.DataFrame(
        [
            {
                "job_id": "flex-1",
                "start_ts": now + pd.Timedelta(minutes=120),
                "end_ts": now + pd.Timedelta(minutes=180),
                "release_ts": now + pd.Timedelta(minutes=90),
                "due_ts": now + pd.Timedelta(minutes=300),
                "required_machines": "CNC-01",
                "shiftable": True,
                "critical": False,
            }
        ]
    )
    candidate = _job_shift_candidate(
        schedule,
        next(schedule.itertuples()),
        now,
        machines,
        15,
        now + pd.Timedelta(minutes=300),
        {"energy_inr_per_kwh": {"off_peak": 6.0, "normal": 7.5, "peak": 9.5}},
    )
    assert candidate is not None
    assert candidate.action == ControlAction.DEFER_JOB
    assert candidate.start == pd.Timestamp("2025-01-01T12:00:00+00:00")
    assert candidate.start + pd.Timedelta(minutes=candidate.duration_min) <= pd.Timestamp(
        schedule.iloc[0].due_ts
    )
