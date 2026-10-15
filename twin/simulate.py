"""Minute-step simplified twin projection; contains no plant simulator imports."""

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from contracts.models import ControlAction, ControlCommand, EquipmentState, KPISet
from twin.config import load_twin_config
from twin.model import MachineParameters, TwinResult, TwinSnapshot


def _power(
    machine: MachineParameters, state: EquipmentState, noise: float, duty: float, consumer: bool
) -> float:
    if state == EquipmentState.OFF:
        return 0.0
    if state == EquipmentState.STANDBY:
        return machine.p_standby_kw
    if state == EquipmentState.WARMUP:
        return 0.7 * machine.p_run_kw
    if state == EquipmentState.IDLE:
        return machine.p_idle_kw
    if machine.equipment_id == "C2":
        loaded_duty = duty if consumer else 0.0
        return loaded_duty * machine.p_run_kw + (1 - loaded_duty) * machine.p_idle_kw
    return max(0.0, machine.p_run_kw * (1 + noise))


def _forecast_masks(
    timestamps: pd.DatetimeIndex, schedule: pd.DataFrame, machines: dict[str, MachineParameters]
) -> dict[str, np.ndarray]:
    masks = {machine_id: np.zeros(len(timestamps), dtype=bool) for machine_id in machines}
    if schedule.empty:
        return masks
    for row in schedule.itertuples():
        start_ix = int(timestamps.searchsorted(pd.Timestamp(row.start_ts), side="left"))
        end_ix = int(timestamps.searchsorted(pd.Timestamp(row.end_ts), side="left"))
        for equipment_id in row.required_machines.split(","):
            if equipment_id not in machines:
                continue
            warmup = machines[equipment_id].warmup_min
            masks[equipment_id][max(0, start_ix - warmup) : min(len(timestamps), end_ix)] = True
            for dependency in machines[equipment_id].needs:
                if dependency in masks:
                    masks[dependency][
                        max(0, start_ix - warmup - machines[dependency].warmup_min) : min(
                            len(timestamps), end_ix
                        )
                    ] = True
    return masks


def _tariff_for_minute(minute: int, tariff: dict[str, Any]) -> float:
    hours = minute // 60
    peak = (9 <= hours < 12) or (18 <= hours < 22)
    off_peak = hours >= 22 or hours < 6
    rates = tariff["energy_inr_per_kwh"]
    if peak:
        return float(rates["peak"])
    if off_peak:
        return float(rates["off_peak"])
    return float(rates["normal"])


def _active_command(
    commands: Iterable[ControlCommand], equipment: str, timestamp: pd.Timestamp
) -> list[ControlCommand]:
    active: list[ControlCommand] = []
    for command in commands:
        if command.equipment_id != equipment or command.issued_at > timestamp.to_pydatetime():
            continue
        if command.duration_min is None or timestamp < pd.Timestamp(
            command.issued_at
        ) + pd.Timedelta(minutes=command.duration_min):
            active.append(command)
    return active


def simulate(
    state: TwinSnapshot,
    schedule: pd.DataFrame,
    controls: Iterable[ControlCommand] | None,
    horizon_min: int,
    scenario: dict[str, Any] | None = None,
    seed: int = 0,
    machines: dict[str, MachineParameters] | None = None,
    facility: dict[str, Any] | None = None,
    tariff: dict[str, Any] | None = None,
) -> TwinResult:
    """Project a scenario from an estimated twin snapshot for ``horizon_min`` minutes."""
    if horizon_min <= 0:
        raise ValueError("horizon_min must be positive")
    if machines is None or facility is None:
        loaded_machines, loaded_facility = load_twin_config("config/facility.yaml")
        machines = machines or loaded_machines
        facility = facility or loaded_facility
    if tariff is None:
        tariff = yaml.safe_load(Path("config/tariff.yaml").read_text(encoding="utf-8"))
    scenario = scenario or {}
    commands = tuple(controls or ())
    rng = np.random.default_rng(seed)
    timestamps = pd.date_range(state.timestamp, periods=horizon_min, freq="min")
    demand = _forecast_masks(timestamps, schedule, machines)
    states = {
        machine_id: state.machine_states.get(machine_id, EquipmentState.OFF)
        for machine_id in machines
    }
    state_age = dict.fromkeys(machines, 0)
    powered_age = dict.fromkeys(machines, 0)
    warmup_age = dict.fromkeys(machines, 0)
    started = {
        machine_id: states[machine_id] not in {EquipmentState.OFF, EquipmentState.STANDBY}
        for machine_id in machines
    }
    state_trace = {machine_id: [] for machine_id in machines}
    per_machine_energy = dict.fromkeys(machines, 0.0)
    main_kw = np.zeros(horizon_min, dtype=float)
    temperature = float(state.temperature_c)
    temperature_trace: list[float] = []
    idle_waste = 0.0
    restarts = 0
    late_jobs: set[str] = set()
    job_ready_minutes: dict[str, int] = {}
    job_expected_minutes: dict[str, int] = {}
    violations: list[str] = []
    temp_capacity_kwh_per_k = float(facility["hvac"]["thermal_capacity_mj_per_k"]) / 3.6
    ua_kw_per_k = float(facility["hvac"]["ua_w_per_k"]) / 1000.0
    lighting_total = float(facility["lighting"]["power_kw_each"]) * len(
        facility["lighting"]["zones"]
    )
    base_kw = float(facility["facility"]["base_load_kw"])
    outdoor_mean = float(scenario.get("weather_mean_c", 30.0))
    shift_end = int(scenario.get("shift_end_hour", 22))

    schedule_by_minute: list[list[Any]] = [[] for _ in range(horizon_min)]
    if not schedule.empty:
        for job in schedule.itertuples():
            start_ix = int(timestamps.searchsorted(pd.Timestamp(job.start_ts), side="left"))
            end_ix = int(timestamps.searchsorted(pd.Timestamp(job.end_ts), side="left"))
            job_key = str(job.job_id)
            job_expected_minutes[job_key] = max(0, min(horizon_min, end_ix) - max(0, start_ix))
            job_ready_minutes[job_key] = 0
            for index in range(max(0, start_ix), min(horizon_min, end_ix)):
                schedule_by_minute[index].append(job)

    for index, timestamp in enumerate(timestamps):
        # Draw for every machine every minute so action/no-action runs share noise.
        noise_draws = {machine_id: float(rng.normal(0.0, 0.04)) for machine_id in machines}
        duty_draws = {machine_id: float(rng.uniform(0.6, 0.9)) for machine_id in machines}
        minute_of_day = timestamp.hour * 60 + timestamp.minute
        active_jobs = schedule_by_minute[index]
        active_machine_ids = {
            mid for job in active_jobs for mid in job.required_machines.split(",")
        }
        component_power: dict[str, float] = {}
        for machine_id, machine in machines.items():
            desired = (
                EquipmentState.RUNNING
                if demand[machine_id][index]
                else (
                    EquipmentState.IDLE
                    if started[machine_id] and 6 * 60 <= minute_of_day < shift_end * 60
                    else EquipmentState.OFF
                )
            )
            if desired == EquipmentState.RUNNING:
                started[machine_id] = True

            active = _active_command(commands, machine_id, timestamp)
            force_standby = any(command.action == ControlAction.STANDBY for command in active)
            if (
                force_standby
                and machine_id not in active_machine_ids
                and states[machine_id] in {EquipmentState.IDLE, EquipmentState.STANDBY}
            ):
                desired = EquipmentState.STANDBY
            if any(command.action == ControlAction.PRE_WARM for command in active):
                desired = EquipmentState.RUNNING
                started[machine_id] = True

            prior = states[machine_id]
            next_state = prior
            if prior == EquipmentState.OFF:
                if desired != EquipmentState.OFF and state_age[machine_id] >= machine.min_off_min:
                    next_state = EquipmentState.STANDBY
            elif prior == EquipmentState.STANDBY:
                if desired in {EquipmentState.RUNNING, EquipmentState.IDLE, EquipmentState.WARMUP}:
                    next_state = EquipmentState.WARMUP
                elif state_age[machine_id] >= machine.min_off_min:
                    next_state = EquipmentState.OFF
            elif prior == EquipmentState.WARMUP:
                warmup_age[machine_id] += 1
                if warmup_age[machine_id] >= machine.warmup_min:
                    next_state = (
                        EquipmentState.RUNNING
                        if desired == EquipmentState.RUNNING
                        else EquipmentState.IDLE
                    )
                elif (
                    desired in {EquipmentState.OFF, EquipmentState.STANDBY}
                    and powered_age[machine_id] >= machine.min_on_min
                ):
                    next_state = EquipmentState.STANDBY
            elif prior == EquipmentState.RUNNING:
                if (
                    desired in {EquipmentState.IDLE, EquipmentState.OFF, EquipmentState.STANDBY}
                    and powered_age[machine_id] >= machine.min_on_min
                ):
                    next_state = EquipmentState.IDLE
            elif prior == EquipmentState.IDLE:
                if desired == EquipmentState.RUNNING:
                    next_state = EquipmentState.RUNNING
                elif (
                    desired in {EquipmentState.OFF, EquipmentState.STANDBY}
                    and powered_age[machine_id] >= machine.min_on_min
                ):
                    next_state = EquipmentState.STANDBY
            if prior != next_state:
                state_age[machine_id] = 0
                if next_state == EquipmentState.WARMUP:
                    warmup_age[machine_id] = 0
                    powered_age[machine_id] = 0
                if prior == EquipmentState.STANDBY and next_state == EquipmentState.WARMUP:
                    restarts += 1
            else:
                state_age[machine_id] += 1
            if next_state in {EquipmentState.OFF, EquipmentState.STANDBY}:
                if next_state == EquipmentState.OFF:
                    powered_age[machine_id] = 0
            else:
                powered_age[machine_id] += 1
            states[machine_id] = next_state
            state_trace[machine_id].append(next_state.value)

        consumer_active = any(
            states[mid] in {EquipmentState.WARMUP, EquipmentState.RUNNING}
            for mid in ("CNC-02", "HP1")
            if mid in states
        )
        if (
            consumer_active
            and "C2" in states
            and states["C2"] in {EquipmentState.OFF, EquipmentState.STANDBY}
        ):
            violations.append(f"dependency:C2:{timestamp.isoformat()}")

        for machine_id, machine in machines.items():
            power = _power(
                machine,
                states[machine_id],
                noise_draws[machine_id],
                duty_draws[machine_id],
                consumer_active,
            )
            component_power[machine_id] = power
            per_machine_energy[machine_id] += power / 60.0
            if states[machine_id] == EquipmentState.IDLE:
                idle_waste += max(0.0, power - machine.p_standby_kw) / 60.0

        # The job is ready only if every required machine is RUNNING; unready work is delayed.
        for job in active_jobs:
            key = str(job.job_id)
            if all(
                states[mid] == EquipmentState.RUNNING
                for mid in job.required_machines.split(",")
                if mid in states
            ):
                job_ready_minutes[key] += 1
            elif timestamp >= pd.Timestamp(job.due_ts):
                late_jobs.add(key)

        lights_off = any(
            command.action == ControlAction.LIGHTS_OFF
            for command in _active_command(commands, "LIGHTS", timestamp)
        )
        lights_kw = 0.0 if lights_off else (lighting_total if 330 <= minute_of_day < 1350 else 0.0)
        people = min(3, len(active_jobs))
        hvac = facility["hvac"]
        setpoint = float(hvac["setpoint_c"])
        setback = [
            command
            for command in _active_command(commands, "HVAC", timestamp)
            if command.action == ControlAction.HVAC_SETBACK
        ]
        if setback:
            setpoint += 2.0
        outdoor = outdoor_mean + 6.0 * np.sin(2 * np.pi * ((minute_of_day / 60.0) - 9.0) / 24.0)
        cop = float(np.clip(4.0 - 0.07 * (outdoor - 25.0), 2.0, 4.5))
        hvac_on = 5 * 60 <= minute_of_day < 23 * 60
        cooling_thermal = (
            min(
                float(hvac["thermal_cap_kw"]),
                max(0.0, (temperature - setpoint) * ua_kw_per_k + 4.0),
            )
            if hvac_on
            else 0.0
        )
        hvac_kw = cooling_thermal / cop + (float(hvac["fan_kw"]) if hvac_on else 0.0)
        heat_kw = (
            ua_kw_per_k * (outdoor - temperature)
            + 0.4 * sum(component_power.values())
            + 0.1 * people
            + 0.9 * lights_kw
            - cooling_thermal
        )
        temperature += heat_kw / max(temp_capacity_kwh_per_k, 1e-6) / 60.0
        temperature_trace.append(temperature)
        if people and not (22.0 <= temperature <= 27.0):
            violations.append(f"comfort:{timestamp.isoformat()}")
        total_kw = sum(component_power.values()) + hvac_kw + lights_kw + base_kw
        main_kw[index] = total_kw

    if not schedule.empty:
        for job in schedule.itertuples():
            key = str(job.job_id)
            if (
                job_expected_minutes.get(key, 0) > 0
                and job_ready_minutes.get(key, 0) < job_expected_minutes[key]
            ):
                late_jobs.add(key)

    slot_mean = pd.Series(main_kw).groupby(np.arange(horizon_min) // 15).mean()
    peak_kw = float(slot_mean.max()) if not slot_mean.empty else 0.0
    energy_kwh = float(main_kw.sum() / 60.0)
    start_minute = state.timestamp.hour * 60 + state.timestamp.minute
    cost = sum(
        main_kw[i] / 60.0 * _tariff_for_minute((start_minute + i) % 1440, tariff)
        for i in range(horizon_min)
    )
    cost += (
        peak_kw
        * float(tariff["demand_charge_inr_per_kw_month"])
        / float(tariff.get("demand_charge_proration_days", 30))
    )
    kpis = KPISet(
        energy_kwh=energy_kwh,
        peak_15min_kw=peak_kw,
        cost_inr=float(cost),
        co2_kg=energy_kwh * float(tariff["grid_factor_kgco2_per_kwh"]),
        idle_waste_kwh=float(idle_waste),
        restarts=int(restarts),
        late_jobs=len(late_jobs),
        comfort_violation_min=sum(value.startswith("comfort:") for value in violations),
    )
    return TwinResult(
        kpis=kpis,
        per_machine_kwh=per_machine_energy,
        temperature_trace_c=temperature_trace,
        state_trace=state_trace,
        constraint_violations=sorted(set(violations)),
        seed=seed,
    )


def simulate_ensemble(
    state: TwinSnapshot,
    schedule: pd.DataFrame,
    controls: Iterable[ControlCommand] | None,
    horizon_min: int,
    scenario: dict[str, Any] | None = None,
    seeds: int = 30,
) -> dict[str, dict[str, float]]:
    """Return mean and 5th/95th percentile for each projected KPI across seeds."""
    if seeds < 1:
        raise ValueError("seeds must be positive")
    runs: list[TwinResult] = []
    for seed in range(seeds):
        uncertainty_rng = np.random.default_rng(np.random.SeedSequence([seed, 4521]))
        uncertain_states = dict(state.machine_states)
        for equipment_id, confidence in state.confidence.items():
            if equipment_id in uncertain_states and uncertainty_rng.random() > confidence:
                choices = [
                    value
                    for value in EquipmentState
                    if value not in {EquipmentState.MAINTENANCE, EquipmentState.FAULT}
                ]
                uncertain_states[equipment_id] = uncertainty_rng.choice(choices)
        scenario_copy = dict(scenario or {})
        scenario_copy["weather_mean_c"] = float(scenario_copy.get("weather_mean_c", 30.0)) + float(
            uncertainty_rng.normal(0.0, float(scenario_copy.get("forecast_error_c", 0.7)))
        )
        perturbed = TwinSnapshot(
            timestamp=state.timestamp,
            machine_states=uncertain_states,
            machine_power_kw=dict(state.machine_power_kw),
            temperature_c=state.temperature_c,
            occupied=state.occupied,
            confidence=dict(state.confidence),
        )
        runs.append(simulate(perturbed, schedule, controls, horizon_min, scenario_copy, seed))
    kpi_names = tuple(type(runs[0].kpis).model_fields)
    return {
        name: {
            "mean": float(np.mean([getattr(run.kpis, name) for run in runs])),
            "p05": float(np.quantile([getattr(run.kpis, name) for run in runs], 0.05)),
            "p95": float(np.quantile([getattr(run.kpis, name) for run in runs], 0.95)),
        }
        for name in kpi_names
    }
