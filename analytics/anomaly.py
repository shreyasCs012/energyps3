"""Transparent anomaly scoring and event-level evaluation utilities."""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

REQUIRED_ESTIMATE_COLUMNS = {"timestamp", "equipment_id", "state", "power_kw_estimate"}


@dataclass
class PowerProfile:
    mean_kw: float
    std_kw: float


@dataclass
class IsolationForestModel:
    estimator: IsolationForest
    feature_columns: tuple[str, ...]
    states: tuple[str, ...]
    equipment_ids: tuple[str, ...]


def _check_estimates(frame: pd.DataFrame) -> None:
    if not REQUIRED_ESTIMATE_COLUMNS.issubset(frame.columns):
        raise ValueError(f"estimate frame must contain {sorted(REQUIRED_ESTIMATE_COLUMNS)}")


def score_power_residuals(
    normal_training: pd.DataFrame,
    evaluation: pd.DataFrame,
    z_threshold: float = 3.0,
) -> pd.DataFrame:
    """Score state-conditional power residuals using only normal training profiles."""
    _check_estimates(normal_training)
    _check_estimates(evaluation)
    if z_threshold <= 0:
        raise ValueError("z_threshold must be positive")
    train = normal_training.copy()
    train["power_kw_estimate"] = pd.to_numeric(train.power_kw_estimate, errors="coerce")
    grouped = train.dropna(subset=["power_kw_estimate"]).groupby(["equipment_id", "state"])[
        "power_kw_estimate"
    ]
    profiles = {
        key: PowerProfile(float(values.mean()), max(float(values.std(ddof=0)), 0.05))
        for key, values in grouped
    }
    rows = evaluation.copy()
    rows["power_kw_estimate"] = pd.to_numeric(rows.power_kw_estimate, errors="coerce")
    means = []
    scales = []
    for row in rows.itertuples():
        profile = profiles.get((row.equipment_id, row.state))
        means.append(profile.mean_kw if profile else np.nan)
        scales.append(profile.std_kw if profile else np.nan)
    rows["expected_kw"] = means
    rows["scale_kw"] = scales
    rows["residual_z"] = (rows.power_kw_estimate - rows.expected_kw) / rows.scale_kw
    rows["anomaly_score"] = rows.residual_z.abs()
    rows["is_anomaly"] = rows.anomaly_score >= z_threshold
    return rows


def _isolation_features(
    estimates: pd.DataFrame,
    states: tuple[str, ...] | None = None,
    equipment_ids: tuple[str, ...] | None = None,
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    _check_estimates(estimates)
    frame = estimates.copy()
    frame["timestamp"] = pd.to_datetime(frame.timestamp)
    frame["hour"] = frame.timestamp.dt.hour + frame.timestamp.dt.minute / 60
    state_levels = states or tuple(sorted(frame.state.astype(str).unique()))
    equipment_levels = equipment_ids or tuple(sorted(frame.equipment_id.astype(str).unique()))
    frame["state_code"] = (
        frame.state.astype(str)
        .map({value: index for index, value in enumerate(state_levels)})
        .fillna(-1)
    )
    frame["equipment_code"] = (
        frame.equipment_id.astype(str)
        .map({value: index for index, value in enumerate(equipment_levels)})
        .fillna(-1)
    )
    features = ("power_kw_estimate", "hour", "state_code", "equipment_code")
    matrix = frame.loc[:, features].apply(pd.to_numeric, errors="coerce")
    return matrix.replace([np.inf, -np.inf], np.nan).fillna(matrix.median()).fillna(0.0), features


def fit_isolation_forest(
    normal_training: pd.DataFrame, contamination: float = 0.02, seed: int = 42
) -> IsolationForestModel:
    """Train an IsolationForest using caller-supplied normal training days only."""
    if not 0 < contamination <= 0.5:
        raise ValueError("contamination must be in (0, 0.5]")
    states = tuple(sorted(normal_training.state.astype(str).unique()))
    equipment_ids = tuple(sorted(normal_training.equipment_id.astype(str).unique()))
    matrix, columns = _isolation_features(normal_training, states, equipment_ids)
    if len(matrix) < 10:
        raise ValueError("at least 10 normal training rows are required")
    model = IsolationForest(
        contamination=contamination, random_state=seed, n_estimators=100, n_jobs=1
    )
    model.fit(matrix.loc[:, columns])
    return IsolationForestModel(model, columns, states, equipment_ids)


def score_isolation_forest(model: IsolationForestModel, evaluation: pd.DataFrame) -> pd.DataFrame:
    matrix, columns = _isolation_features(evaluation, model.states, model.equipment_ids)
    if columns != model.feature_columns:
        raise ValueError("evaluation features do not match the fitted model")
    result = evaluation.copy()
    result["anomaly_score"] = -model.estimator.score_samples(matrix.loc[:, columns])
    result["is_anomaly"] = model.estimator.predict(matrix.loc[:, columns]) == -1
    return result


def threshold_alerts(meter: pd.DataFrame, threshold_kw: float) -> pd.DataFrame:
    """P1 comparator: emit an alert for each 15-minute meter interval over threshold."""
    if threshold_kw <= 0 or not {"interval_start", "main_kw"}.issubset(meter.columns):
        raise ValueError("positive threshold and interval_start/main_kw meter columns are required")
    result = meter.loc[:, ["interval_start", "main_kw"]].copy()
    result = result.rename(columns={"interval_start": "timestamp"})
    result["timestamp"] = pd.to_datetime(result.timestamp)
    result["is_anomaly"] = result.main_kw > threshold_kw
    result["anomaly_score"] = result.main_kw / threshold_kw
    result["equipment_id"] = "FACILITY"
    return result


def event_level_metrics(
    labels: pd.DataFrame,
    predictions: pd.DataFrame,
    interval_minutes: int = 1,
) -> dict[str, object]:
    """Match prediction hits to labeled event intervals and report delay by type.

    Machinery predictions match by equipment. Facility-wide threshold alerts match by
    time only. An event counts detected once, at its first hit.
    """
    required_labels = {
        "event_id",
        "date",
        "anomaly_type",
        "equipment_id",
        "start_minute",
        "end_minute",
    }
    if not required_labels.issubset(labels.columns):
        raise ValueError(f"labels must contain {sorted(required_labels)}")
    required_predictions = {"timestamp", "is_anomaly"}
    if not required_predictions.issubset(predictions.columns):
        raise ValueError(f"predictions must contain {sorted(required_predictions)}")
    if interval_minutes < 1:
        raise ValueError("interval_minutes must be positive")
    events = labels.copy()
    events["event_date"] = pd.to_datetime(events.date).dt.date
    predicted = predictions.copy()
    predicted["timestamp"] = pd.to_datetime(predicted.timestamp)
    predicted = predicted[predicted.is_anomaly.astype(bool)]
    matches: list[dict[str, object]] = []
    matched_indices: set[int] = set()
    for event in events.itertuples():
        hits = predicted[
            (predicted.timestamp.dt.date == event.event_date)
            & (
                predicted.timestamp.dt.hour * 60 + predicted.timestamp.dt.minute
                >= event.start_minute
            )
            & (predicted.timestamp.dt.hour * 60 + predicted.timestamp.dt.minute < event.end_minute)
        ]
        if "equipment_id" in hits and event.equipment_id != "FACILITY":
            hits = hits[hits.equipment_id.astype(str) == str(event.equipment_id)]
        if hits.empty:
            matches.append(
                {
                    "event_id": event.event_id,
                    "anomaly_type": event.anomaly_type,
                    "detected": False,
                    "delay_min": np.nan,
                }
            )
        else:
            first = hits.timestamp.min()
            delay = max(0.0, (first.hour * 60 + first.minute - event.start_minute))
            matches.append(
                {
                    "event_id": event.event_id,
                    "anomaly_type": event.anomaly_type,
                    "detected": True,
                    "delay_min": delay,
                }
            )
            matched_indices.update(hits.index.tolist())
    match_frame = pd.DataFrame(
        matches, columns=["event_id", "anomaly_type", "detected", "delay_min"]
    )
    detected_count = int(match_frame.detected.sum()) if not match_frame.empty else 0
    event_count = len(events)
    false_alerts = 0
    if not predicted.empty:
        predicted["equipment_id"] = predicted.get("equipment_id", "FACILITY")
        gap_limit = pd.Timedelta(minutes=interval_minutes * 1.5)
        for _, group in predicted.groupby(
            [predicted.timestamp.dt.date, "equipment_id"], sort=False
        ):
            group = group.sort_values("timestamp")
            cluster_end = None
            cluster_index: list[int] = []
            clusters: list[list[int]] = []
            for row in group.itertuples():
                if cluster_end is None or row.timestamp - cluster_end > gap_limit:
                    if cluster_index:
                        clusters.append(cluster_index)
                    cluster_index = [row.Index]
                else:
                    cluster_index.append(row.Index)
                cluster_end = row.timestamp
            if cluster_index:
                clusters.append(cluster_index)
            false_alerts += sum(
                1 for indices in clusters if not any(index in matched_indices for index in indices)
            )
    precision = (
        detected_count / (detected_count + false_alerts) if detected_count + false_alerts else 0.0
    )
    recall = detected_count / event_count if event_count else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    per_type = {}
    for anomaly_type, group in match_frame.groupby("anomaly_type") if not match_frame.empty else []:
        per_type[str(anomaly_type)] = {
            "events": int(len(group)),
            "detected": int(group.detected.sum()),
            "recall": float(group.detected.mean()),
            "mean_detection_delay_min": float(group.delay_min.mean())
            if group.detected.any()
            else None,
        }
    return {
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "detection_delay_min": float(match_frame.delay_min.mean()) if detected_count else None,
        "events": int(event_count),
        "detected_events": detected_count,
        "false_alerts": int(false_alerts),
        "by_anomaly_type": per_type,
    }
