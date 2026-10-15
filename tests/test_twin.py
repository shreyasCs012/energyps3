from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from contracts.models import ControlAction, ControlCommand, EquipmentState
from plant.simulator import load_facility, simulate_day
from policies.baseline import evaluate as baseline_policy
from policies.rule_idle_shutdown import evaluate as idle_policy
from policies.threshold_alert import evaluate as threshold_policy
from twin.calibrate import calibrate_from_estimates, calibrate_thermal
from twin.config import load_twin_config
from twin.estimator import estimate_states, snapshot_from_estimates
from twin.model import MachineParameters, TwinSnapshot
from twin.simulate import simulate, simulate_ensemble
from twin.what_if import what_if


@pytest.fixture(scope="module")
def inputs():
    facility = load_facility("config/facility.yaml")
    run = simulate_day(date(2025, 2, 1), 71, facility, cv_mode="simulated")
    parameters, _ = load_twin_config("config/facility.yaml")
    return facility, run, parameters


def test_estimator_ignores_plant_truth_and_uses_meter_cv_schedule(inputs):
    facility, run, parameters = inputs
    estimate = estimate_states(
        run.telemetry, run.meter_15min, run.cv_events, run.schedule, facility, run.hvac, parameters
    )
    corrupted = run.telemetry.copy()
    corrupted["state_true"] = EquipmentState.FAULT.value
    corrupted["operator_present_true"] = ~corrupted.operator_present_true
    other = estimate_states(
        corrupted, run.meter_15min, run.cv_events, run.schedule, facility, run.hvac, parameters
    )
    pd.testing.assert_frame_equal(estimate, other)
    assert len(estimate) == 5 * 1440
    assert set(estimate.evidence).issubset(
        {"submeter", "submeter+cv", "submeter/cv_disagree", "cv", "schedule", "main_meter_residual"}
    )
    residual = estimate_states(
        run.telemetry,
        run.meter_15min,
        run.cv_events.iloc[:0],
        run.schedule,
        facility,
        run.hvac,
        parameters,
    )
    assert (
        residual.loc[residual.equipment_id == "CNC-02", "evidence"] == "main_meter_residual"
    ).any()


def test_calibration_improves_heldout_power_mape():
    params = {"M1": MachineParameters("M1", 6.5, 2.2, 0.4, 4, 0.5, 5, 3, submetered=True)}
    rows = []
    for day in range(3):
        for state_index, (state, power) in enumerate(
            (("STANDBY", 0.6), ("IDLE", 3.0), ("RUNNING", 7.2))
        ):
            for minute in range(20):
                rows.append(
                    {
                        "timestamp": pd.Timestamp("2025-01-01", tz="UTC")
                        + pd.Timedelta(days=day, minutes=state_index * 20 + minute),
                        "equipment_id": "M1",
                        "state": state,
                        "power_kw_estimate": power,
                    }
                )
    heldout_meter = pd.DataFrame(
        {
            "interval_start": [
                pd.Timestamp("2025-01-03", tz="UTC") + pd.Timedelta(minutes=15 * index)
                for index in range(4)
            ],
            "main_kw": [2.4, 4.0, 6.2, 9.0],
        }
    )
    heldout_hvac = pd.DataFrame(
        {
            "timestamp": [
                pd.Timestamp("2025-01-03", tz="UTC") + pd.Timedelta(minutes=i) for i in range(60)
            ],
            "hvac_power_kw": [1.0] * 60,
        }
    )
    facility = {"facility": {"base_load_kw": 0.8}, "lighting": {"zones": [], "power_kw_each": 1.4}}
    report = calibrate_from_estimates(
        params,
        pd.DataFrame(rows),
        heldout_days=1,
        training_days=2,
        main_meter=heldout_meter,
        hvac=heldout_hvac,
        facility=facility,
    )
    assert report.after_mape["M1"] < report.before_mape["M1"]
    assert report.main_meter_after_mape is not None
    assert report.main_meter_after_mape < report.main_meter_before_mape
    assert report.calibrated["M1"].p_run_kw == pytest.approx(7.2)


def test_thermal_least_squares_recovers_configured_scale():
    rng = np.random.default_rng(3)
    capacity = 18 / 3.6
    ua = 0.9
    temp = 24.0
    rows = []
    for minute in range(500):
        outdoor = 29 + 4 * np.sin(minute / 50)
        heat = 3.0 + float(rng.uniform(0, 1))
        cooling = 1.0 + float(rng.uniform(0, 1))
        rows.append(
            {
                "indoor_temp_c": temp,
                "outdoor_temp_c": outdoor,
                "internal_heat_kw": heat,
                "cooling_thermal_kw": cooling,
            }
        )
        temp += (ua * (outdoor - temp) + heat - cooling) / capacity / 60
    fitted = calibrate_thermal(pd.DataFrame(rows))
    assert fitted["ua_w_per_k"] == pytest.approx(900, rel=0.02)
    assert fitted["capacity_mj_per_k"] == pytest.approx(18, rel=0.02)


def test_common_random_number_what_if_and_ensemble():
    facility = load_facility("config/facility.yaml")
    parameters, _ = load_twin_config("config/facility.yaml")
    timestamp = datetime(2025, 1, 1, 8, tzinfo=UTC)
    snapshot = TwinSnapshot(
        timestamp=timestamp,
        machine_states={machine_id: EquipmentState.IDLE for machine_id in parameters},
        machine_power_kw={
            machine_id: machine.p_idle_kw for machine_id, machine in parameters.items()
        },
    )
    cmd = ControlCommand(
        command_id="test-standby",
        issued_at=timestamp,
        equipment_id="CNC-01",
        action=ControlAction.STANDBY,
        duration_min=90,
        rationale="test action",
    )
    result = what_if(snapshot, pd.DataFrame(), cmd, 90, {"weather_mean_c": 30}, seed=5)
    assert result.delta["energy_kwh"] > 0
    assert result.baseline.seed == result.action.seed == 5
    assert len(result.action.temperature_trace_c) == 90
    ensemble = simulate_ensemble(snapshot, pd.DataFrame(), [], 30, {"weather_mean_c": 30}, seeds=3)
    assert set(ensemble["energy_kwh"]) == {"mean", "p05", "p95"}
    assert ensemble["energy_kwh"]["p95"] >= ensemble["energy_kwh"]["p05"]
    assert (
        simulate(
            snapshot, pd.DataFrame(), [], 10, seed=5, machines=parameters, facility=facility
        ).kpis.energy_kwh
        > 0
    )


def test_snapshot_and_policy_outputs(inputs):
    facility, run, parameters = inputs
    estimates = estimate_states(
        run.telemetry, run.meter_15min, run.cv_events, run.schedule, facility, run.hvac, parameters
    )
    snapshot = snapshot_from_estimates(
        estimates, run.telemetry.timestamp.max(), temperature_c=24.5, occupied=True
    )
    assert set(snapshot.machine_states) == set(parameters)
    assert snapshot.occupied
    assert baseline_policy().commands == []
    alerts = threshold_policy(
        pd.DataFrame({"interval_start": [datetime.now(UTC)], "main_kw": [100.0]}), 35
    )
    assert alerts.alerts and not alerts.commands
    idle_rows = pd.DataFrame(
        {
            "timestamp": [
                datetime(2025, 1, 1, 8, tzinfo=UTC) + timedelta(minutes=i) for i in range(20)
            ],
            "equipment_id": ["CNC-01"] * 20,
            "state": [EquipmentState.IDLE.value] * 20,
        }
    )
    commands = idle_policy(idle_rows, idle_minutes=15).commands
    assert len(commands) == 1
    assert commands[0].action == ControlAction.STANDBY
