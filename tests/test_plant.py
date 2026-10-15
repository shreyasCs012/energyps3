from datetime import date

import numpy as np
import pytest

from contracts.models import EquipmentState
from plant.generate import _choose_anomalies
from plant.simulator import load_facility, simulate_day
from plant.state_machine import MachineState, is_legal_transition


@pytest.fixture(scope="module")
def facility():
    return load_facility("config/facility.yaml")


def test_machine_state_machine_enforces_warmup_and_dwell():
    machine = MachineState(state_minutes=0)
    args = {"min_on_min": 4, "min_off_min": 2, "warmup_min": 2}
    assert machine.advance(EquipmentState.RUNNING, **args) == EquipmentState.OFF
    assert machine.advance(EquipmentState.RUNNING, **args) == EquipmentState.OFF
    assert machine.advance(EquipmentState.RUNNING, **args) == EquipmentState.STANDBY
    assert machine.advance(EquipmentState.RUNNING, **args) == EquipmentState.WARMUP
    assert machine.advance(EquipmentState.RUNNING, **args) == EquipmentState.WARMUP
    assert machine.advance(EquipmentState.RUNNING, **args) == EquipmentState.RUNNING
    assert machine.advance(EquipmentState.OFF, **args) == EquipmentState.RUNNING
    assert machine.advance(EquipmentState.OFF, **args) == EquipmentState.IDLE
    assert machine.advance(EquipmentState.OFF, **args) == EquipmentState.STANDBY
    assert all(
        is_legal_transition(a, b)
        for a, b in zip(
            [
                EquipmentState.OFF,
                EquipmentState.OFF,
                EquipmentState.STANDBY,
                EquipmentState.WARMUP,
                EquipmentState.WARMUP,
                EquipmentState.RUNNING,
                EquipmentState.RUNNING,
                EquipmentState.RUNNING,
                EquipmentState.IDLE,
            ],
            [
                EquipmentState.OFF,
                EquipmentState.STANDBY,
                EquipmentState.WARMUP,
                EquipmentState.WARMUP,
                EquipmentState.RUNNING,
                EquipmentState.RUNNING,
                EquipmentState.RUNNING,
                EquipmentState.IDLE,
                EquipmentState.STANDBY,
            ],
            strict=True,
        )
    )
    assert not is_legal_transition(EquipmentState.OFF, EquipmentState.RUNNING)


def test_same_seed_reproduces_plant_and_cv(facility):
    first = simulate_day(date(2025, 1, 1), 17, facility, cv_mode="simulated")
    second = simulate_day(date(2025, 1, 1), 17, facility, cv_mode="simulated")
    assert first.physical_parameters == second.physical_parameters
    assert first.components_minute.equals(second.components_minute)
    assert first.telemetry.equals(second.telemetry)
    assert first.cv_events.equals(second.cv_events)


def test_machine_and_meter_contracts_and_energy_conservation(facility):
    run = simulate_day(date(2025, 1, 2), 29, facility, cv_mode="oracle")
    assert len(run.telemetry) == 5 * 1440
    assert len(run.meter_15min) == 96
    assert run.telemetry.loc[~run.telemetry.submetered, "power_kw"].isna().all()
    components = run.components_minute
    expected = components[["machines_kw", "hvac_kw", "lighting_kw", "base_kw"]].sum(axis=1)
    np.testing.assert_allclose(expected, components.main_meter_true_kw, rtol=0, atol=1e-10)
    assert np.max(np.abs(components.main_meter_kw - expected) / expected) < 0.01
    states = run.telemetry.pivot(index="timestamp", columns="equipment_id", values="state_true")
    consumer_active = states[["CNC-02", "HP1"]].isin(["WARMUP", "RUNNING"]).any(axis=1)
    compressor_ready = ~states["C2"].isin(["OFF", "STANDBY"])
    assert (compressor_ready[consumer_active]).all()
    for equipment_id, telemetry in run.telemetry.groupby("equipment_id", sort=True):
        events = run.cv_events[run.cv_events.machine_id == equipment_id].sort_values("timestamp")
        telemetry = telemetry.sort_values("timestamp")
        assert events.state.reset_index(drop=True).equals(
            telemetry.state_true.reset_index(drop=True)
        )


def test_baseline_daily_energy_mix_is_in_calibrated_range(facility):
    run = simulate_day(
        date(2025, 1, 3), 42, facility, {"weather_mean_c": 30, "p_forget": 0.0}, cv_mode="oracle"
    )
    energy = run.components_minute[["machines_kw", "hvac_kw", "lighting_kw", "base_kw"]].sum()
    shares = energy / energy.sum()
    assert 0.58 <= shares["machines_kw"] <= 0.75
    assert 0.12 <= shares["hvac_kw"] <= 0.27
    # Three 1.4 kW zones stay on for 17 hours per the supplied baseline assumption.
    assert 0.10 <= shares["lighting_kw"] <= 0.17
    assert 0.025 <= shares["base_kw"] <= 0.06
    assert run.schedule.duration_min.between(45, 240).all()


def test_seeded_true_parameters_are_within_nameplate_bounds(facility):
    run = simulate_day(date(2025, 1, 4), 53, facility, cv_mode="oracle")
    for machine in facility["machines"]:
        for name in ("p_run_kw", "p_idle_kw", "p_standby_kw"):
            value = run.physical_parameters[f"{machine['id']}.{name}"]
            assert 0.9 * machine[name] <= value <= 1.1 * machine[name]
    assert (
        0.9 * facility["hvac"]["ua_w_per_k"]
        <= run.physical_parameters["hvac.ua_w_per_k"]
        <= 1.1 * facility["hvac"]["ua_w_per_k"]
    )


def test_anomaly_split_keeps_training_clean_and_includes_unseen_test_types():
    rng = np.random.default_rng(8)
    assert _choose_anomalies("train", 0, rng) == []
    assert _choose_anomalies("test", 5, rng)[0] == "sensor_spike"
    assert _choose_anomalies("test", 6, rng)[0] == "sensor_dropout"
