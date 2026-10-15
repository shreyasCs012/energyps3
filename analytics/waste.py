"""Rule-based waste/root-cause labels and an optional supervised classifier."""

from collections.abc import Mapping

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report

ROOT_CAUSES = (
    "idle_waste",
    "schedule_mismatch",
    "abnormal_load",
    "equipment_inefficiency",
    "normal",
)
FEATURE_COLUMNS = (
    "power_kw_estimate",
    "p_standby_kw",
    "idle_duration_min",
    "scheduled_active",
    "scheduled_use_next_min",
    "residual_z",
)


def build_waste_features(
    estimates: pd.DataFrame,
    schedule: pd.DataFrame,
    machine_parameters: Mapping[str, object],
) -> pd.DataFrame:
    """Derive rule/classifier features without consuming plant truth labels."""
    required = {"timestamp", "equipment_id", "state", "power_kw_estimate"}
    if not required.issubset(estimates.columns):
        raise ValueError(f"estimates must contain {sorted(required)}")
    if (
        not {"start_ts", "end_ts", "required_machines"}.issubset(schedule.columns)
        and not schedule.empty
    ):
        raise ValueError("schedule must contain start_ts, end_ts, and required_machines")
    rows = estimates.copy()
    rows["timestamp"] = pd.to_datetime(rows.timestamp)
    rows = rows.sort_values(["equipment_id", "timestamp"]).reset_index(drop=True)
    rows["p_standby_kw"] = rows.equipment_id.map(
        {
            equipment_id: float(machine.p_standby_kw)
            for equipment_id, machine in machine_parameters.items()
        }
    )
    rows["p_idle_kw"] = rows.equipment_id.map(
        {
            equipment_id: float(machine.p_idle_kw)
            for equipment_id, machine in machine_parameters.items()
        }
    )
    if "residual_z" in rows:
        rows["residual_z"] = pd.to_numeric(rows.residual_z, errors="coerce").fillna(0.0)
    else:
        rows["residual_z"] = 0.0
    rows["scheduled_active"] = False
    rows["scheduled_use_next_min"] = np.inf
    if not schedule.empty:
        jobs = schedule.copy()
        jobs["start_ts"] = pd.to_datetime(jobs.start_ts)
        jobs["end_ts"] = pd.to_datetime(jobs.end_ts)
        for equipment_id, indices in rows.groupby("equipment_id", sort=False).groups.items():
            equipment_jobs = jobs[
                jobs.required_machines.astype(str).map(
                    lambda value, name=equipment_id: name in value.split(",")
                )
            ]
            if equipment_jobs.empty:
                continue
            timestamps = pd.DatetimeIndex(rows.loc[indices, "timestamp"])
            active = np.zeros(len(timestamps), dtype=bool)
            for job in equipment_jobs.itertuples():
                active |= (timestamps >= job.start_ts) & (timestamps < job.end_ts)
            rows.loc[indices, "scheduled_active"] = active

            starts = pd.DatetimeIndex(equipment_jobs.start_ts.sort_values())
            offsets = starts.as_unit("ns").asi8
            at = timestamps.as_unit("ns").asi8
            positions = offsets.searchsorted(at, side="left")
            has_next = positions < len(offsets)
            next_use = np.full(len(timestamps), np.inf)
            next_use[has_next] = np.maximum(
                0.0, (offsets[positions[has_next]] - at[has_next]) / 60_000_000_000
            )
            rows.loc[indices, "scheduled_use_next_min"] = next_use
    rows["idle_duration_min"] = 0
    for _, indices in rows.groupby("equipment_id", sort=False).groups.items():
        group = rows.loc[indices]
        changes = group.state.ne(group.state.shift()) | (
            group.timestamp.diff().dt.total_seconds().gt(60.1)
        )
        run_ids = changes.cumsum()
        duration = group.groupby(run_ids, sort=False).cumcount().to_numpy() + 1
        duration[group.state.to_numpy() != "IDLE"] = 0
        rows.loc[indices, "idle_duration_min"] = duration
    return rows


def classify_waste(
    estimates: pd.DataFrame,
    schedule: pd.DataFrame,
    machine_parameters: Mapping[str, object],
    residual_z_threshold: float = 2.5,
) -> pd.DataFrame:
    """Apply auditable root-cause rules, including the specified idle-waste rule."""
    frame = build_waste_features(estimates, schedule, machine_parameters)
    if residual_z_threshold <= 0:
        raise ValueError("residual_z_threshold must be positive")
    frame["root_cause"] = "normal"
    for equipment_id, machine in machine_parameters.items():
        p_idle = float(machine.p_idle_kw)
        p_standby = float(machine.p_standby_kw)
        break_even = (
            float(machine.restart_kwh) / (p_idle - p_standby) * 60
            if p_idle > p_standby
            else float("inf")
        )
        gap = max(int(machine.min_off_min), break_even)
        mask = (
            (frame.equipment_id == equipment_id)
            & (frame.state == "IDLE")
            & (frame.power_kw_estimate > 1.5 * p_standby)
            & (~frame.scheduled_active)
            & (frame.scheduled_use_next_min > gap)
            & (frame.idle_duration_min > 10)
        )
        frame.loc[mask, "root_cause"] = "idle_waste"
    mismatch = frame.scheduled_active & ~frame.state.isin(["RUNNING", "WARMUP"])
    frame.loc[mismatch & frame.root_cause.eq("normal"), "root_cause"] = "schedule_mismatch"
    high_residual = frame.residual_z.abs() >= residual_z_threshold
    running = frame.state.eq("RUNNING")
    frame.loc[high_residual & running, "root_cause"] = "equipment_inefficiency"
    frame.loc[high_residual & ~running & frame.root_cause.eq("normal"), "root_cause"] = (
        "abnormal_load"
    )
    return frame


def fit_root_cause_classifier(
    labeled_features: pd.DataFrame, seed: int = 42
) -> RandomForestClassifier:
    """Fit the optional RandomForest on explicitly labeled training rows."""
    required = {*FEATURE_COLUMNS, "root_cause"}
    if not required.issubset(labeled_features.columns):
        raise ValueError(f"training frame must contain {sorted(required)}")
    unknown = set(labeled_features.root_cause.dropna().unique()) - set(ROOT_CAUSES)
    if unknown:
        raise ValueError(f"unknown root-cause labels: {sorted(unknown)}")
    model = RandomForestClassifier(
        n_estimators=200,
        max_depth=8,
        class_weight="balanced",
        random_state=seed,
        n_jobs=1,
    )
    features = labeled_features.loc[:, FEATURE_COLUMNS].replace([np.inf, -np.inf], np.nan)
    model.fit(features.fillna(0.0), labeled_features.root_cause)
    return model


def evaluate_root_cause_classifier(
    model: RandomForestClassifier, labeled_features: pd.DataFrame
) -> dict[str, object]:
    """Return held-out class precision/recall/F1 and confusion matrix payload."""
    required = {*FEATURE_COLUMNS, "root_cause"}
    if not required.issubset(labeled_features.columns):
        raise ValueError(f"evaluation frame must contain {sorted(required)}")
    actual = labeled_features.root_cause.astype(str)
    features = labeled_features.loc[:, FEATURE_COLUMNS].replace([np.inf, -np.inf], np.nan)
    predicted = model.predict(features.fillna(0.0))
    report = classification_report(
        actual, predicted, labels=list(ROOT_CAUSES), output_dict=True, zero_division=0
    )
    matrix = pd.crosstab(actual, pd.Series(predicted, index=actual.index), dropna=False)
    return {
        "classification_report": report,
        "confusion_matrix": matrix.to_dict(),
        "labels": list(ROOT_CAUSES),
    }
