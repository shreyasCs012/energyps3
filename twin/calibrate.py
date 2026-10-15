"""Least-squares calibration of twin load profiles and a simplified thermal model."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from contracts.models import EquipmentState
from twin.model import MachineParameters


@dataclass
class CalibrationReport:
    calibrated: dict[str, MachineParameters]
    before_mape: dict[str, float]
    after_mape: dict[str, float]
    thermal_parameters: dict[str, float]
    main_meter_before_mape: float | None = None
    main_meter_after_mape: float | None = None


def _mape(actual: np.ndarray, predicted: np.ndarray) -> float:
    keep = np.isfinite(actual) & np.isfinite(predicted) & (np.abs(actual) > 0.1)
    if not keep.any():
        return 0.0
    return float(np.mean(np.abs(actual[keep] - predicted[keep]) / np.abs(actual[keep])) * 100.0)


def _predict_profiles(frame: pd.DataFrame, parameters: dict[str, MachineParameters]) -> np.ndarray:
    values = np.zeros(len(frame), dtype=float)
    for equipment_id, indices in frame.groupby("equipment_id", sort=False).groups.items():
        machine = parameters[equipment_id]
        rows = frame.loc[indices]
        levels = {
            EquipmentState.OFF.value: 0.0,
            EquipmentState.STANDBY.value: machine.p_standby_kw,
            EquipmentState.WARMUP.value: 0.7 * machine.p_run_kw,
            EquipmentState.IDLE.value: machine.p_idle_kw,
            EquipmentState.RUNNING.value: machine.p_run_kw,
        }
        values[frame.index.get_indexer(indices)] = rows.state.map(levels).fillna(0.0).to_numpy()
    return values


def calibrate_profiles(
    parameters: dict[str, MachineParameters],
    training_estimates: pd.DataFrame,
    heldout_estimates: pd.DataFrame,
    thermal_observations: pd.DataFrame | None = None,
    heldout_main_meter: pd.DataFrame | None = None,
    heldout_hvac: pd.DataFrame | None = None,
    facility: dict | None = None,
) -> CalibrationReport:
    """Fit per-machine idle/standby/run levels from training estimates only.

    Estimated-state labels and meter-derived powers are the only inputs; plant-side
    true-state columns are not accepted or consulted.
    """
    required = {"equipment_id", "state", "power_kw_estimate"}
    if not required.issubset(training_estimates.columns) or not required.issubset(
        heldout_estimates.columns
    ):
        raise ValueError(f"estimate frames must contain {sorted(required)}")
    calibrated = {key: MachineParameters(**vars(value)) for key, value in parameters.items()}
    for equipment_id, machine in calibrated.items():
        sample = training_estimates[
            (training_estimates.equipment_id == equipment_id)
            & training_estimates.state.isin(
                [
                    EquipmentState.STANDBY.value,
                    EquipmentState.IDLE.value,
                    EquipmentState.RUNNING.value,
                ]
            )
            & np.isfinite(training_estimates.power_kw_estimate)
        ]
        if sample.empty:
            continue
        states = sample.state.to_numpy()
        design = np.column_stack(
            [
                states == EquipmentState.STANDBY.value,
                states == EquipmentState.IDLE.value,
                states == EquipmentState.RUNNING.value,
            ]
        ).astype(float)
        values, *_ = np.linalg.lstsq(
            design, sample.power_kw_estimate.to_numpy(dtype=float), rcond=None
        )
        present = design.sum(axis=0) > 0
        if present[0]:
            machine.p_standby_kw = max(0.0, float(values[0]))
        if present[1]:
            machine.p_idle_kw = max(0.0, float(values[1]))
        if present[2]:
            machine.p_run_kw = max(0.0, float(values[2]))

    heldout = heldout_estimates.copy().reset_index(drop=True)
    actual = heldout.power_kw_estimate.to_numpy(dtype=float)
    before = _predict_profiles(heldout, parameters)
    after = _predict_profiles(heldout, calibrated)
    before_mape: dict[str, float] = {}
    after_mape: dict[str, float] = {}
    for equipment_id in parameters:
        mask = heldout.equipment_id.to_numpy() == equipment_id
        before_mape[equipment_id] = _mape(actual[mask], before[mask])
        after_mape[equipment_id] = _mape(actual[mask], after[mask])

    thermal = calibrate_thermal(thermal_observations) if thermal_observations is not None else {}
    main_before = main_after = None
    if heldout_main_meter is not None and facility is not None:
        main_before = _main_meter_mape(
            heldout, parameters, heldout_main_meter, facility, heldout_hvac
        )
        main_after = _main_meter_mape(
            heldout, calibrated, heldout_main_meter, facility, heldout_hvac
        )
    return CalibrationReport(calibrated, before_mape, after_mape, thermal, main_before, main_after)


def calibrate_from_estimates(
    parameters: dict[str, MachineParameters],
    estimates: pd.DataFrame,
    heldout_days: int = 1,
    training_days: int | None = None,
    thermal_observations: pd.DataFrame | None = None,
    main_meter: pd.DataFrame | None = None,
    hvac: pd.DataFrame | None = None,
    facility: dict | None = None,
) -> CalibrationReport:
    """Fit on the first days and report MAPE on a later held-out day window."""
    if heldout_days < 1:
        raise ValueError("heldout_days must be positive")
    dates = sorted(pd.to_datetime(estimates.timestamp).dt.date.unique())
    if len(dates) <= heldout_days:
        raise ValueError("need at least one training day plus the held-out day window")
    training_dates = dates[:-heldout_days]
    if training_days is not None:
        if training_days < 1:
            raise ValueError("training_days must be positive")
        training_dates = training_dates[:training_days]
    validation_dates = dates[-heldout_days:]
    day_values = pd.to_datetime(estimates.timestamp).dt.date
    train = estimates.loc[day_values.isin(training_dates)].copy()
    heldout = estimates.loc[day_values.isin(validation_dates)].copy()
    heldout_meter = main_meter
    heldout_hvac = hvac
    if main_meter is not None:
        meter_dates = pd.to_datetime(main_meter.interval_start).dt.date
        heldout_meter = main_meter.loc[meter_dates.isin(validation_dates)].copy()
    if hvac is not None:
        hvac_dates = pd.to_datetime(hvac.timestamp).dt.date
        heldout_hvac = hvac.loc[hvac_dates.isin(validation_dates)].copy()
    return calibrate_profiles(
        parameters, train, heldout, thermal_observations, heldout_meter, heldout_hvac, facility
    )


def _main_meter_mape(
    heldout: pd.DataFrame,
    parameters: dict[str, MachineParameters],
    main_meter: pd.DataFrame,
    facility: dict,
    hvac: pd.DataFrame | None,
) -> float:
    if heldout.empty or main_meter.empty or "main_kw" not in main_meter.columns:
        return 0.0
    estimates = heldout.reset_index(drop=True).copy()
    estimates["profile_kw"] = _predict_profiles(estimates, parameters)
    per_minute = estimates.groupby("timestamp", sort=True).profile_kw.sum()
    times = pd.DatetimeIndex(per_minute.index)
    if hvac is not None and not hvac.empty and "hvac_power_kw" in hvac.columns:
        hvac_values = hvac.copy()
        hvac_values["timestamp"] = pd.to_datetime(hvac_values.timestamp)
        hvac_series = (
            hvac_values.drop_duplicates("timestamp")
            .set_index("timestamp")
            .hvac_power_kw.sort_index()
        )
        hvac_kw = hvac_series.reindex(times, method="ffill").fillna(0.0).to_numpy(dtype=float)
    else:
        hvac_kw = np.zeros(len(times), dtype=float)
    lighting = facility.get("lighting", {})
    minute_of_day = times.hour * 60 + times.minute
    lights_on = (minute_of_day >= 330) & (minute_of_day < 1350)
    light_kw = (
        lights_on * float(lighting.get("power_kw_each", 0.0)) * len(lighting.get("zones", []))
    )
    total = (
        per_minute.to_numpy(dtype=float)
        + hvac_kw
        + light_kw
        + float(facility.get("facility", {}).get("base_load_kw", 0.0))
    )
    prediction = pd.Series(total, index=times).groupby(times.floor("15min")).mean()
    meter = main_meter.copy()
    meter["interval_start"] = pd.to_datetime(meter.interval_start)
    actual = meter.set_index("interval_start").main_kw.sort_index()
    joined = pd.concat([actual.rename("actual"), prediction.rename("predicted")], axis=1).dropna()
    return _mape(joined.actual.to_numpy(dtype=float), joined.predicted.to_numpy(dtype=float))


def calibrate_thermal(observations: pd.DataFrame) -> dict[str, float]:
    """Fit effective UA and thermal capacity from minute temperature/heat traces.

    Expected columns are indoor_temp_c, outdoor_temp_c, internal_heat_kw, and
    cooling_thermal_kw. The fitted model is C*dT = UA*(Tout-T) + heat - cooling.
    """
    required = {"indoor_temp_c", "outdoor_temp_c", "internal_heat_kw", "cooling_thermal_kw"}
    if not required.issubset(observations.columns):
        raise ValueError(f"thermal observations must contain {sorted(required)}")
    frame = observations.loc[:, sorted(required)].apply(pd.to_numeric, errors="coerce").dropna()
    if len(frame) < 3:
        return {}
    temp = frame.indoor_temp_c.to_numpy(dtype=float)
    delta = np.diff(temp)
    outdoor_delta = frame.outdoor_temp_c.to_numpy(dtype=float)[:-1] - temp[:-1]
    heat_minus_cooling = (
        frame.internal_heat_kw.to_numpy(dtype=float)[:-1]
        - frame.cooling_thermal_kw.to_numpy(dtype=float)[:-1]
    )
    design = np.column_stack([outdoor_delta, heat_minus_cooling])
    coeffs, *_ = np.linalg.lstsq(design, delta, rcond=None)
    ua_per_capacity, inverse_capacity = (float(value) for value in coeffs)
    if inverse_capacity <= 0 or ua_per_capacity <= 0:
        return {}
    capacity_kwh_per_k = 1 / (60 * inverse_capacity)
    ua_kw_per_k = ua_per_capacity / inverse_capacity
    return {"ua_w_per_k": ua_kw_per_k * 1000, "capacity_mj_per_k": capacity_kwh_per_k * 3.6}
