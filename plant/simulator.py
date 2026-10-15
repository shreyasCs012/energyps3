"""Minute-resolution ground-truth plant and independent physical parameters."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from contracts.models import ControlAction, ControlCommand, EquipmentState
from plant.schedule import generate_schedule
from plant.state_machine import MachineState

STATE_BY_NAME = {state.value: state for state in EquipmentState}
KNOWN_ANOMALIES = (
    "forgotten_on",
    "compressor_leak",
    "bearing_degradation",
    "lights_left_on",
    "hvac_overcool",
)
UNSEEN_ANOMALIES = ("sensor_spike", "sensor_dropout")


@dataclass
class PlantRun:
    """All artifacts produced by one seeded simulated plant day."""

    telemetry: pd.DataFrame
    meter_15min: pd.DataFrame
    hvac: pd.DataFrame
    weather: pd.DataFrame
    schedule: pd.DataFrame
    anomaly_labels: pd.DataFrame
    cv_events: pd.DataFrame
    components_minute: pd.DataFrame
    physical_parameters: dict[str, float]
    command_outcomes: list[dict[str, Any]]


def load_facility(path: str | Path) -> dict[str, Any]:
    """Load YAML facility configuration."""
    with Path(path).open(encoding="utf-8") as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, dict) or not value.get("machines"):
        raise ValueError("Facility config must define a non-empty machines list")
    return value


def _label_anomalies(day: date, anomaly_types: list[str], rng: np.random.Generator) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for index, anomaly in enumerate(anomaly_types):
        start_minute = int(rng.integers(7 * 60, 20 * 60))
        if anomaly == "forgotten_on":
            start_minute = 22 * 60
            end_minute = 24 * 60
            equipment = str(rng.choice(["CNC-01", "CNC-02", "HP1", "CV1"]))
        elif anomaly == "lights_left_on":
            start_minute = 22 * 60 + 30
            end_minute = 24 * 60
            equipment = str(rng.choice(["Z1", "Z2", "Z3"]))
        else:
            end_minute = min(24 * 60, start_minute + int(rng.integers(30, 121)))
            equipment = (
                "C2"
                if anomaly == "compressor_leak"
                else ("HVAC" if anomaly == "hvac_overcool" else "CNC-01")
            )
        records.append(
            {
                "event_id": f"{day:%Y%m%d}-A{index + 1:02d}",
                "date": day.isoformat(),
                "anomaly_type": anomaly,
                "equipment_id": equipment,
                "start_minute": start_minute,
                "end_minute": end_minute,
            }
        )
    return pd.DataFrame(
        records,
        columns=["event_id", "date", "anomaly_type", "equipment_id", "start_minute", "end_minute"],
    )


def _event_masks(labels: pd.DataFrame) -> dict[tuple[str, str], np.ndarray]:
    masks: dict[tuple[str, str], np.ndarray] = {}
    for row in labels.itertuples():
        mask = masks.setdefault((row.anomaly_type, row.equipment_id), np.zeros(1440, dtype=bool))
        mask[int(row.start_minute) : int(row.end_minute)] = True
    return masks


def simulate_day(
    day: date,
    seed: int,
    facility: dict[str, Any],
    scenario: dict[str, Any] | None = None,
    anomaly_types: list[str] | None = None,
    cv_mode: str = "simulated",
    controls: Iterable[ControlCommand] | None = None,
) -> PlantRun:
    """Simulate a seeded day; optional commands are applied by plant truth."""
    if cv_mode not in {"oracle", "simulated"}:
        raise ValueError(
            "cv_mode must be 'oracle' or 'simulated' until the Phase 4 video pipeline exists"
        )
    scenario = scenario or {}
    plant_rng = np.random.default_rng(seed)
    label_rng = np.random.default_rng(np.random.SeedSequence([seed, 1777]))
    cv_rng = np.random.default_rng(np.random.SeedSequence([seed, 2819]))
    weather_rng = np.random.default_rng(np.random.SeedSequence([seed, 3931]))
    command_rng = np.random.default_rng(np.random.SeedSequence([seed, 9847]))
    labels = _label_anomalies(day, anomaly_types or [], label_rng)
    schedule = generate_schedule(
        day,
        np.random.default_rng(np.random.SeedSequence([seed, 991])),
        bool(scenario.get("short_shift", False)),
    )
    for column in ("release_ts", "start_ts", "end_ts", "due_ts"):
        schedule[column] = pd.to_datetime(schedule[column]).dt.tz_localize(
            facility["facility"].get("timezone", "Asia/Kolkata")
        )
    anomaly_masks = _event_masks(labels)

    machines = facility["machines"]
    by_id = {machine["id"]: machine for machine in machines}
    machine_ids = [machine["id"] for machine in machines]
    stochastic = {
        machine_id: np.random.default_rng(np.random.SeedSequence([seed, 13_001, index]))
        for index, machine_id in enumerate(machine_ids)
    }
    run_innovations = {
        machine_id: stochastic[machine_id].normal(0.0, 0.04, size=1440)
        for machine_id in machine_ids
    }
    compressor_duty = {
        machine_id: stochastic[machine_id].uniform(0.6, 0.9, size=1440)
        for machine_id in machine_ids
    }
    compressor_leak_noise = {
        machine_id: stochastic[machine_id].uniform(0.15, 0.25, size=1440)
        for machine_id in machine_ids
    }
    degradation_noise = {
        machine_id: stochastic[machine_id].uniform(0.08, 0.15, size=1440)
        for machine_id in machine_ids
    }
    sensor_noise = {
        machine_id: stochastic[machine_id].normal(0.0, 0.005, size=1440)
        for machine_id in machine_ids
    }
    meter_noise = np.random.default_rng(np.random.SeedSequence([seed, 45_129])).normal(
        0.0, 0.002, size=1440
    )
    true_params: dict[str, float] = {}
    for machine in machines:
        for name in ("p_run_kw", "p_idle_kw", "p_standby_kw"):
            true_params[f"{machine['id']}.{name}"] = float(machine[name]) * plant_rng.uniform(
                0.9, 1.1
            )
    true_params["hvac.ua_w_per_k"] = float(facility["hvac"]["ua_w_per_k"]) * plant_rng.uniform(
        0.9, 1.1
    )
    true_params["hvac.capacity_mj_per_k"] = float(
        facility["hvac"]["thermal_capacity_mj_per_k"]
    ) * plant_rng.uniform(0.9, 1.1)

    timestamps = pd.date_range(
        start=pd.Timestamp(
            datetime.combine(day, datetime.min.time()),
            tz=facility["facility"].get("timezone", "Asia/Kolkata"),
        ),
        periods=1440,
        freq="min",
    )
    command_outcomes: list[dict[str, Any]] = []
    command_intervals: list[tuple[int, int, ControlCommand]] = []
    for command in controls or ():
        issued_minute = int((pd.Timestamp(command.issued_at) - timestamps[0]).total_seconds() // 60)
        latency = int(command_rng.integers(1, 3))
        failed = bool(command_rng.random() < 0.02)
        effective_minute = issued_minute + latency
        finish_minute = effective_minute + (command.duration_min or 1440)
        if not failed:
            command_intervals.append((effective_minute, finish_minute, command))
        command_outcomes.append(
            {
                "command_id": command.command_id,
                "action": command.action.value,
                "equipment_id": command.equipment_id,
                "issued_minute": issued_minute,
                "effective_minute": effective_minute,
                "latency_min": latency,
                "failed": failed,
                "executed": False,
            }
        )
    machine_states = {machine["id"]: MachineState() for machine in machines}
    ar_load = {machine["id"]: 0.0 for machine in machines}
    outdoor = np.empty(1440, dtype=float)
    temp_c = 25.0
    temp_trace = np.empty(1440, dtype=float)
    machine_kw = {machine["id"]: np.zeros(1440, dtype=float) for machine in machines}
    machine_state = {machine["id"]: np.empty(1440, dtype=object) for machine in machines}
    operator_present = {machine["id"]: np.zeros(1440, dtype=bool) for machine in machines}
    lighting_kw = np.zeros(1440, dtype=float)
    hvac_kw = np.zeros(1440, dtype=float)
    base_kw = np.full(1440, float(facility["facility"]["base_load_kw"]))
    cooling_kw_th = np.zeros(1440, dtype=float)
    people_n = np.zeros(1440, dtype=int)
    shift_end = 18 if scenario.get("short_shift") else 22
    machine_started = {machine["id"]: False for machine in machines}
    natural_forgot_until: dict[str, int] = {}
    p_forget = float(np.clip(scenario.get("p_forget", 0.0), 0.0, 1.0))
    for machine in machines:
        if plant_rng.random() < p_forget:
            natural_forgot_until[machine["id"]] = shift_end * 60 + int(plant_rng.integers(60, 181))
    demand_masks = {machine["id"]: np.zeros(1440, dtype=bool) for machine in machines}
    scheduled_presence = {machine["id"]: np.zeros(1440, dtype=bool) for machine in machines}
    job_count = np.zeros(1440, dtype=int)
    for job in schedule.itertuples():
        start_minute = int(pd.Timestamp(job.start_ts).hour * 60 + pd.Timestamp(job.start_ts).minute)
        end_minute = int(pd.Timestamp(job.end_ts).hour * 60 + pd.Timestamp(job.end_ts).minute)
        job_count[start_minute:end_minute] += 1
        for machine_id in job.required_machines.split(","):
            machine = by_id[machine_id]
            warm_start = max(0, start_minute - int(machine["warmup_min"]))
            demand_masks[machine_id][warm_start:end_minute] = True
            scheduled_presence[machine_id][start_minute:end_minute] = True
            if machine_id != "C2" and "C2" in machine.get("needs", []):
                compressor_warm = int(by_id["C2"]["warmup_min"])
                demand_masks["C2"][max(0, warm_start - compressor_warm) : end_minute] = True

    def event_active(anomaly: str, equipment: str, minute: int) -> bool:
        mask = anomaly_masks.get((anomaly, equipment))
        return bool(mask[minute]) if mask is not None else False

    # A machine stays available/IDLE across within-shift gaps after its first job.
    for minute in range(1440):
        hour = minute / 60.0
        mean_temp = float(scenario.get("weather_mean_c", 30.0))
        diurnal = mean_temp + 6.0 * np.sin(2 * np.pi * (hour - 9.0) / 24.0)
        previous = outdoor[minute - 1] if minute else diurnal
        outdoor[minute] = (
            diurnal
            + 0.85
            * (previous - (mean_temp + 6.0 * np.sin(2 * np.pi * ((hour - 1 / 60) - 9.0) / 24.0)))
            + weather_rng.normal(0, 0.35)
        )

        # Two or three operators while jobs are active; absent during gaps/break periods.
        is_break = (
            minute in range(10 * 60, 10 * 60 + 15)
            or minute in range(12 * 60, 12 * 60 + 30)
            or minute in range(18 * 60, 18 * 60 + 15)
        )
        people = 0 if is_break else min(3, int(job_count[minute]))
        people_n[minute] = people

        desired: dict[str, EquipmentState] = {}
        for machine in machines:
            machine_id = machine["id"]
            running = bool(demand_masks[machine_id][minute])
            if running:
                machine_started[machine_id] = True
            if running:
                desired[machine_id] = EquipmentState.RUNNING
            elif machine_started[machine_id] and 6 * 60 <= minute < shift_end * 60:
                desired[machine_id] = EquipmentState.IDLE
            else:
                desired[machine_id] = EquipmentState.OFF
            if shift_end * 60 <= minute < natural_forgot_until.get(machine_id, 0):
                desired[machine_id] = EquipmentState.IDLE

        # Baseline forgotten-on behavior is separately labeled only on anomaly days.
        forgotten = labels[labels.anomaly_type == "forgotten_on"] if not labels.empty else labels
        if not forgotten.empty:
            for row in forgotten.itertuples():
                if minute >= row.start_minute and row.equipment_id in desired:
                    desired[row.equipment_id] = EquipmentState.IDLE

        active_controls = [
            command for start, end, command in command_intervals if start <= minute < end
        ]
        active_command_ids = {command.command_id for command in active_controls}
        for outcome in command_outcomes:
            if outcome["command_id"] in active_command_ids:
                outcome["executed"] = True
        for command in active_controls:
            if command.action in {ControlAction.STANDBY, ControlAction.PRE_WARM}:
                if command.equipment_id in desired:
                    desired[command.equipment_id] = (
                        EquipmentState.STANDBY
                        if command.action == ControlAction.STANDBY
                        else EquipmentState.RUNNING
                    )

        actual: dict[str, EquipmentState] = {}
        for machine in machines:
            machine_id = machine["id"]
            actual[machine_id] = machine_states[machine_id].advance(
                desired[machine_id],
                min_on_min=int(machine["min_on_min"]),
                min_off_min=int(machine["min_off_min"]),
                warmup_min=int(machine["warmup_min"]),
            )
            machine_state[machine_id][minute] = actual[machine_id].value
            operator_present[machine_id][minute] = bool(
                people and scheduled_presence[machine_id][minute] and not is_break
            )

        consumers = any(
            actual[machine_id] in {EquipmentState.WARMUP, EquipmentState.RUNNING}
            for machine_id in ("CNC-02", "HP1")
        )
        if consumers and actual["C2"] in {EquipmentState.OFF, EquipmentState.STANDBY}:
            # A production start is held until the dependency has reached a powered state.
            actual["CNC-02"] = (
                EquipmentState.IDLE
                if actual["CNC-02"] == EquipmentState.RUNNING
                else actual["CNC-02"]
            )
            actual["HP1"] = (
                EquipmentState.IDLE if actual["HP1"] == EquipmentState.RUNNING else actual["HP1"]
            )

        for machine in machines:
            machine_id = machine["id"]
            state = actual[machine_id]
            if state == EquipmentState.OFF:
                watts = 0.0
            elif state == EquipmentState.STANDBY:
                watts = true_params[f"{machine_id}.p_standby_kw"]
            elif state == EquipmentState.WARMUP:
                watts = 0.7 * true_params[f"{machine_id}.p_run_kw"]
            elif state == EquipmentState.IDLE:
                watts = true_params[f"{machine_id}.p_idle_kw"]
            elif state == EquipmentState.RUNNING:
                ar_load[machine_id] = (
                    0.85 * ar_load[machine_id] + run_innovations[machine_id][minute]
                )
                if machine_id == "C2":
                    duty = float(compressor_duty[machine_id][minute]) if consumers else 0.0
                    if event_active("compressor_leak", "C2", minute):
                        duty = min(1.0, duty + float(compressor_leak_noise[machine_id][minute]))
                    watts = (
                        duty * true_params[f"{machine_id}.p_run_kw"]
                        + (1 - duty) * true_params[f"{machine_id}.p_idle_kw"]
                    )
                else:
                    watts = true_params[f"{machine_id}.p_run_kw"] * (1 + ar_load[machine_id])
                    if event_active("bearing_degradation", machine_id, minute):
                        watts *= 1 + float(degradation_noise[machine_id][minute])
            else:
                watts = 0.0
            machine_kw[machine_id][minute] = max(0.0, watts)

        zone_power = 0.0
        for zone in facility["lighting"]["zones"]:
            baseline_on = 5 * 60 + 30 <= minute < 22 * 60 + 30
            forced = event_active("lights_left_on", zone, minute)
            zone_off = any(
                command.action == ControlAction.LIGHTS_OFF
                and command.equipment_id in {"LIGHTS", f"LIGHTS:{zone}"}
                for command in active_controls
            )
            if (baseline_on or forced) and not zone_off:
                zone_power += float(facility["lighting"]["power_kw_each"])
        lighting_kw[minute] = zone_power

        hvac = facility["hvac"]
        hvac_on = 5 * 60 <= minute < 23 * 60
        overcool = event_active("hvac_overcool", "HVAC", minute)
        setpoint = 21.0 if overcool else float(hvac["setpoint_c"])
        setbacks = [
            command
            for command in active_controls
            if command.action == ControlAction.HVAC_SETBACK and command.equipment_id == "HVAC"
        ]
        if setbacks:
            setpoint += max(command.setpoint_delta_c or 2.0 for command in setbacks)
        cop = float(np.clip(4.0 - 0.07 * (outdoor[minute] - 25), 2.0, 4.5))
        if hvac_on and temp_c > setpoint:
            thermal_kw = min(
                float(hvac["thermal_cap_kw"]),
                max(0.0, (temp_c - setpoint) * true_params["hvac.ua_w_per_k"] / 1000.0 + 4.0),
            )
        else:
            thermal_kw = 0.0
        cooling_kw_th[minute] = thermal_kw
        hvac_kw[minute] = thermal_kw / cop + (float(hvac["fan_kw"]) if hvac_on else 0.0)
        machine_heat = sum(machine_kw[machine_id][minute] for machine_id in machine_kw) * 0.4
        lights_heat = 0.9 * lighting_kw[minute]
        people_heat = 0.1 * people
        heat_kw = (
            (outdoor[minute] - temp_c) * true_params["hvac.ua_w_per_k"] / 1000.0
            + machine_heat
            + lights_heat
            + people_heat
            - thermal_kw
        )
        temp_c += heat_kw / (true_params["hvac.capacity_mj_per_k"] * 1000 / 3600) / 60.0
        temp_trace[minute] = temp_c

    # Build observed telemetry. Non-submetered machine power is intentionally absent.
    telemetry_rows: list[dict[str, Any]] = []
    for machine in machines:
        machine_id = machine["id"]
        for minute, timestamp in enumerate(timestamps):
            state = machine_state[machine_id][minute]
            has_submeter = bool(machine.get("submetered", False))
            observed = (
                machine_kw[machine_id][minute] * (1 + sensor_noise[machine_id][minute])
                if has_submeter
                else np.nan
            )
            if event_active("sensor_dropout", machine_id, minute):
                observed = np.nan
            if event_active("sensor_spike", machine_id, minute):
                observed = max(0.0, float(observed if np.isfinite(observed) else 0) + 4.0)
            telemetry_rows.append(
                {
                    "timestamp": timestamp,
                    "equipment_id": machine_id,
                    "power_kw": observed,
                    "state_true": state,
                    "operator_present_true": operator_present[machine_id][minute],
                    "submetered": has_submeter,
                }
            )
    telemetry = pd.DataFrame(telemetry_rows)
    weather = pd.DataFrame({"timestamp": timestamps, "outdoor_temp_c": outdoor})
    hvac_frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "indoor_temp_c": temp_trace,
            "hvac_power_kw": hvac_kw,
            "cooling_thermal_kw": cooling_kw_th,
            "occupied_true": people_n > 0,
        }
    )
    machine_frame = pd.DataFrame({machine_id: values for machine_id, values in machine_kw.items()})
    actual_total = machine_frame.sum(axis=1).to_numpy() + hvac_kw + lighting_kw + base_kw
    components = pd.DataFrame(
        {
            "timestamp": timestamps,
            "machines_kw": machine_frame.sum(axis=1),
            "hvac_kw": hvac_kw,
            "lighting_kw": lighting_kw,
            "base_kw": base_kw,
            "main_meter_true_kw": actual_total,
        }
    )
    components["main_meter_kw"] = actual_total * (1 + meter_noise)
    for machine_id, values in machine_frame.items():
        components[f"machine:{machine_id}_kw"] = values.to_numpy()
    minute_frame = components.set_index("timestamp")
    agg = (
        minute_frame[
            [
                "machines_kw",
                "hvac_kw",
                "lighting_kw",
                "base_kw",
                "main_meter_true_kw",
                "main_meter_kw",
            ]
        ]
        .resample("15min")
        .agg(
            {
                "machines_kw": "mean",
                "hvac_kw": "mean",
                "lighting_kw": "mean",
                "base_kw": "mean",
                "main_meter_true_kw": "mean",
                "main_meter_kw": "mean",
            }
        )
    )
    agg["energy_kwh"] = minute_frame["main_meter_true_kw"].resample("15min").sum() / 60
    agg = agg.reset_index().rename(
        columns={"timestamp": "interval_start", "main_meter_kw": "main_kw"}
    )

    cv_rows: list[dict[str, Any]] = []
    accuracy = 1.0 if cv_mode == "oracle" else 0.92
    flicker = 0.0 if cv_mode == "oracle" else 0.03
    for machine_id in machine_state:
        prior_state: str | None = None
        for minute, timestamp in enumerate(timestamps):
            truth = str(machine_state[machine_id][minute])
            estimated = truth
            if cv_rng.random() > accuracy:
                estimated = str(
                    cv_rng.choice(
                        [
                            s.value
                            for s in EquipmentState
                            if s.value in {"OFF", "STANDBY", "IDLE", "RUNNING"} and s.value != truth
                        ]
                    )
                )
            if prior_state and cv_rng.random() < flicker:
                estimated = prior_state
            prior_state = estimated
            cv_rows.append(
                {
                    "timestamp": timestamp,
                    "event_id": f"{day:%Y%m%d}-{machine_id}-{minute:04d}",
                    "camera_id": f"cam-{machine_id}",
                    "machine_id": machine_id,
                    "zone_id": None,
                    "state": truth if cv_mode == "oracle" else estimated,
                    "operator_present": bool(operator_present[machine_id][minute]),
                    "lights_on": lighting_kw[minute] > 0,
                    "confidence": 1.0 if cv_mode == "oracle" else float(cv_rng.uniform(0.7, 0.99)),
                    "clip_id": None,
                }
            )
    return PlantRun(
        telemetry=telemetry,
        meter_15min=agg,
        hvac=hvac_frame,
        weather=weather,
        schedule=schedule,
        anomaly_labels=labels,
        cv_events=pd.DataFrame(cv_rows),
        components_minute=components,
        physical_parameters=true_params,
        command_outcomes=command_outcomes,
    )
