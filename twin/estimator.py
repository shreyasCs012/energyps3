"""Fuse meters, schedule, and CV observations into twin-side equipment estimates."""

from typing import Any

import numpy as np
import pandas as pd

from contracts.models import EquipmentState
from twin.model import MachineParameters, TwinSnapshot

OBSERVABLE_TELEMETRY_COLUMNS = ("timestamp", "equipment_id", "power_kw", "submetered")
OBSERVABLE_CV_COLUMNS = ("timestamp", "machine_id", "state", "confidence", "lights_on")
STATE_POWER = (
    EquipmentState.OFF,
    EquipmentState.STANDBY,
    EquipmentState.WARMUP,
    EquipmentState.IDLE,
    EquipmentState.RUNNING,
)


def _power_levels(parameters: MachineParameters) -> np.ndarray:
    return np.array(
        [
            0.0,
            parameters.p_standby_kw,
            0.7 * parameters.p_run_kw,
            parameters.p_idle_kw,
            parameters.p_run_kw,
        ],
        dtype=float,
    )


def _schedule_masks(
    timestamps: pd.DatetimeIndex,
    schedule: pd.DataFrame,
    machines: dict[str, MachineParameters],
) -> dict[str, np.ndarray]:
    masks = {machine_id: np.zeros(len(timestamps), dtype=bool) for machine_id in machines}
    if schedule.empty:
        return masks
    for row in schedule.itertuples():
        start = pd.Timestamp(row.start_ts)
        end = pd.Timestamp(row.end_ts)
        start_ix = max(0, int(timestamps.searchsorted(start, side="left")))
        end_ix = min(len(timestamps), int(timestamps.searchsorted(end, side="left")))
        for equipment_id in row.required_machines.split(","):
            parameters = machines.get(equipment_id)
            if parameters is None:
                continue
            warm_start = max(0, start_ix - parameters.warmup_min)
            masks[equipment_id][warm_start:end_ix] = True
            for dependency in parameters.needs:
                if dependency in masks:
                    masks[dependency][
                        max(0, warm_start - machines[dependency].warmup_min) : end_ix
                    ] = True
    return masks


def estimate_states(
    telemetry: pd.DataFrame,
    main_meter: pd.DataFrame,
    cv_events: pd.DataFrame,
    schedule: pd.DataFrame,
    facility: dict[str, Any],
    hvac: pd.DataFrame | None = None,
    parameters: dict[str, MachineParameters] | None = None,
) -> pd.DataFrame:
    """Estimate state/power per machine using only observed fields and configuration.

    Plant truth columns such as ``state_true`` and ``operator_present_true`` are never
    read. The main-meter residual is apportioned across non-submetered machines.
    """
    if parameters is None:
        parameters = {
            item["id"]: MachineParameters(
                equipment_id=item["id"],
                p_run_kw=float(item["p_run_kw"]),
                p_idle_kw=float(item["p_idle_kw"]),
                p_standby_kw=float(item["p_standby_kw"]),
                warmup_min=int(item["warmup_min"]),
                restart_kwh=float(item["restart_kwh"]),
                min_off_min=int(item["min_off_min"]),
                min_on_min=int(item["min_on_min"]),
                needs=tuple(item.get("needs", [])),
                submetered=bool(item.get("submetered", False)),
            )
            for item in facility["machines"]
        }
    if telemetry.empty:
        return pd.DataFrame(
            columns=[
                "timestamp",
                "equipment_id",
                "state",
                "power_kw_estimate",
                "confidence",
                "evidence",
            ]
        )

    observed = telemetry.loc[
        :, [column for column in OBSERVABLE_TELEMETRY_COLUMNS if column in telemetry.columns]
    ].copy()
    timestamps = pd.DatetimeIndex(
        pd.to_datetime(observed.timestamp).drop_duplicates().sort_values()
    )
    time_count = len(timestamps)
    main = main_meter.loc[:, ["interval_start", "main_kw"]].copy()
    main["interval_start"] = pd.to_datetime(main.interval_start)
    main_series = (
        main.drop_duplicates("interval_start").set_index("interval_start").main_kw.sort_index()
    )
    main_by_minute = main_series.reindex(timestamps, method="ffill").to_numpy(dtype=float)
    if hvac is not None and not hvac.empty and "hvac_power_kw" in hvac.columns:
        hvac_series = hvac.loc[:, ["timestamp", "hvac_power_kw"]].copy()
        hvac_series["timestamp"] = pd.to_datetime(hvac_series.timestamp)
        hvac_by_minute = (
            hvac_series.drop_duplicates("timestamp")
            .set_index("timestamp")
            .hvac_power_kw.reindex(timestamps)
            .to_numpy(dtype=float)
        )
        hvac_by_minute = np.nan_to_num(hvac_by_minute, nan=0.0)
    else:
        hvac_by_minute = np.zeros(time_count, dtype=float)

    minute_of_day = timestamps.hour * 60 + timestamps.minute
    lighting = facility.get("lighting", {})
    light_power = float(lighting.get("power_kw_each", 0.0)) * len(lighting.get("zones", []))
    lights_on = (minute_of_day >= (5 * 60 + 30)) & (minute_of_day < (22 * 60 + 30))
    lights_by_minute = lights_on.astype(float) * light_power
    base_kw = float(facility.get("facility", {}).get("base_load_kw", 0.0))
    schedule_mask = _schedule_masks(timestamps, schedule, parameters)

    cv_observed = cv_events.loc[
        :, [column for column in OBSERVABLE_CV_COLUMNS if column in cv_events.columns]
    ].copy()
    if not cv_observed.empty:
        cv_observed["timestamp"] = pd.to_datetime(cv_observed.timestamp)
        cv_observed = cv_observed.drop_duplicates(["timestamp", "machine_id"], keep="last")
        if "lights_on" in cv_observed.columns:
            observed_lights = cv_observed.groupby("timestamp").lights_on.max().reindex(timestamps)
            lights_by_minute = (
                observed_lights.fillna(pd.Series(lights_on, index=timestamps))
                .astype(float)
                .to_numpy()
                * light_power
            )

    expected: dict[str, np.ndarray] = {}
    states: dict[str, np.ndarray] = {}
    confidence: dict[str, np.ndarray] = {}
    evidence: dict[str, np.ndarray] = {}
    observed_power: dict[str, np.ndarray] = {}
    for equipment_id, machine in parameters.items():
        rows = observed[observed.equipment_id == equipment_id].drop_duplicates(
            "timestamp", keep="last"
        )
        power_series = (
            rows.set_index("timestamp").power_kw.reindex(timestamps)
            if "power_kw" in rows
            else pd.Series(np.nan, index=timestamps)
        )
        power = power_series.to_numpy(dtype=float)
        observed_power[equipment_id] = power
        levels = _power_levels(machine)
        state_ix = np.argmin(np.abs(power[:, None] - levels[None, :]), axis=1)
        inferred_state = np.array([STATE_POWER[index].value for index in state_ix], dtype=object)
        inferred_conf = np.full(time_count, 0.45, dtype=float)
        source = np.full(time_count, "schedule", dtype=object)
        valid_power = np.isfinite(power)
        inferred_conf[valid_power] = 0.82
        source[valid_power] = "submeter"

        if not cv_observed.empty and "machine_id" in cv_observed.columns:
            machine_cv = cv_observed[cv_observed.machine_id == equipment_id]
            if not machine_cv.empty:
                cv_indexed = machine_cv.set_index("timestamp").reindex(timestamps)
                cv_state = cv_indexed.state.to_numpy(dtype=object)
                cv_conf = cv_indexed.confidence.to_numpy(dtype=float)
                cv_valid = pd.notna(cv_state) & np.isfinite(cv_conf) & (cv_conf >= 0.55)
                use_cv = cv_valid & (~valid_power | (not machine.submetered))
                inferred_state[use_cv] = cv_state[use_cv]
                inferred_conf[use_cv] = cv_conf[use_cv]
                source[use_cv] = "cv"
                consistent = cv_valid & valid_power & (cv_state == inferred_state)
                inferred_conf[consistent] = np.maximum(
                    inferred_conf[consistent], cv_conf[consistent]
                )
                source[consistent] = "submeter+cv"
                conflict = cv_valid & valid_power & (cv_state != inferred_state)
                inferred_conf[conflict] = np.minimum(inferred_conf[conflict], 0.7)
                source[conflict] = "submeter/cv_disagree"

        scheduled = schedule_mask[equipment_id]
        use_schedule = scheduled & (inferred_state == EquipmentState.OFF.value) & (source != "cv")
        inferred_state[use_schedule] = EquipmentState.WARMUP.value
        inferred_conf[use_schedule] = 0.68
        source[use_schedule] = "schedule"

        expected_power = np.choose(
            np.array(
                [STATE_POWER.index(EquipmentState(value)) for value in inferred_state], dtype=int
            ),
            levels,
        )
        expected[equipment_id] = expected_power
        states[equipment_id] = inferred_state
        confidence[equipment_id] = inferred_conf
        evidence[equipment_id] = source

    submetered_ids = [
        machine_id for machine_id, machine in parameters.items() if machine.submetered
    ]
    measured_submeter_total = np.zeros(time_count, dtype=float)
    for machine_id in submetered_ids:
        power = observed_power[machine_id]
        measured_submeter_total += np.where(np.isfinite(power), power, expected[machine_id])
    residual = np.maximum(
        0.0, main_by_minute - measured_submeter_total - hvac_by_minute - lights_by_minute - base_kw
    )
    non_submetered = [
        machine_id for machine_id, machine in parameters.items() if not machine.submetered
    ]
    expected_total = sum(
        (expected[machine_id] for machine_id in non_submetered), start=np.zeros(time_count)
    )
    scale = np.divide(
        residual, expected_total, out=np.zeros(time_count), where=expected_total > 1e-6
    )
    scale = np.clip(scale, 0.0, 2.0)

    output: list[pd.DataFrame] = []
    for equipment_id, machine in parameters.items():
        if machine.submetered:
            measured = observed_power[equipment_id]
            estimated_power = np.where(np.isfinite(measured), measured, expected[equipment_id])
            missing = ~np.isfinite(measured)
            inferred_from_power = np.argmin(
                np.abs(estimated_power[:, None] - _power_levels(machine)[None, :]), axis=1
            )
            fallback_state = np.array(
                [STATE_POWER[index].value for index in inferred_from_power], dtype=object
            )
            no_cv = evidence[equipment_id] != "cv"
            states[equipment_id][missing & no_cv] = fallback_state[missing & no_cv]
        else:
            estimated_power = expected[equipment_id] * scale
            cv_state = states[equipment_id]
            has_cv = evidence[equipment_id] == "cv"
            state_ix = np.argmin(
                np.abs(estimated_power[:, None] - _power_levels(machine)[None, :]), axis=1
            )
            residual_state = np.array(
                [STATE_POWER[index].value for index in state_ix], dtype=object
            )
            no_strong_evidence = (confidence[equipment_id] < 0.7) & ~has_cv
            states[equipment_id][no_strong_evidence] = residual_state[no_strong_evidence]
            confidence[equipment_id][no_strong_evidence] = 0.62
            source = evidence[equipment_id].copy()
            source[no_strong_evidence] = "main_meter_residual"
            evidence[equipment_id] = source

        output.append(
            pd.DataFrame(
                {
                    "timestamp": timestamps,
                    "equipment_id": equipment_id,
                    "state": states[equipment_id],
                    "power_kw_estimate": np.maximum(0.0, estimated_power),
                    "confidence": confidence[equipment_id],
                    "evidence": evidence[equipment_id],
                }
            )
        )
    return pd.concat(output, ignore_index=True).sort_values(
        ["timestamp", "equipment_id"], ignore_index=True
    )


def snapshot_from_estimates(
    estimates: pd.DataFrame,
    timestamp: Any,
    temperature_c: float = 24.0,
    occupied: bool = False,
) -> TwinSnapshot:
    """Build the current twin state from the latest available estimate per machine."""
    if estimates.empty:
        raise ValueError("cannot build a twin snapshot from empty estimates")
    moment = pd.Timestamp(timestamp)
    history = estimates[pd.to_datetime(estimates.timestamp) <= moment]
    if history.empty:
        raise ValueError("no estimate exists at or before the requested timestamp")
    latest = history.sort_values("timestamp").groupby("equipment_id", sort=True).tail(1)
    return TwinSnapshot(
        timestamp=moment.to_pydatetime(),
        machine_states={row.equipment_id: EquipmentState(row.state) for row in latest.itertuples()},
        machine_power_kw={
            row.equipment_id: float(row.power_kw_estimate) for row in latest.itertuples()
        },
        temperature_c=float(temperature_c),
        occupied=bool(occupied),
        confidence={row.equipment_id: float(row.confidence) for row in latest.itertuples()},
    )
