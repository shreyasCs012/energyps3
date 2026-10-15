"""Day-split evaluation harness for Phase 3 analytics baselines."""

import json
from pathlib import Path
from typing import Any

import pandas as pd
from sklearn.metrics import classification_report, confusion_matrix

from analytics.anomaly import (
    event_level_metrics,
    fit_isolation_forest,
    score_isolation_forest,
    score_power_residuals,
    threshold_alerts,
)
from analytics.forecast import walk_forward_evaluate
from analytics.waste import (
    build_waste_features,
    classify_waste,
    evaluate_root_cause_classifier,
    fit_root_cause_classifier,
)
from plant.simulator import load_facility
from twin.config import load_twin_config
from twin.estimator import estimate_states

ANOMALY_TO_ROOT_CAUSE = {
    "forgotten_on": "idle_waste",
    "compressor_leak": "abnormal_load",
    "bearing_degradation": "equipment_inefficiency",
    "sensor_spike": "abnormal_load",
    "sensor_dropout": "abnormal_load",
}


def _read_split(root: Path, name: str, split: str) -> pd.DataFrame:
    path = root / f"{name}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"missing generated dataset table: {path}")
    frame = pd.read_parquet(path)
    if "split" not in frame:
        raise ValueError(f"{path} is missing the day-level split column")
    return frame.loc[frame.split == split].copy()


def _estimates_for_split(
    root: Path, split: str, facility: dict[str, Any], parameters: dict
) -> pd.DataFrame:
    return estimate_states(
        _read_split(root, "telemetry_1min", split),
        _read_split(root, "main_meter_15min", split),
        _read_split(root, "cv_events", split),
        _read_split(root, "schedule", split),
        facility,
        _read_split(root, "hvac_temp", split),
        parameters,
    )


def _attach_root_cause_truth(predictions: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    comparable = labels[labels.anomaly_type.isin(ANOMALY_TO_ROOT_CAUSE)].copy()
    comparable["date"] = pd.to_datetime(comparable.date).dt.date
    rows = predictions.copy()
    rows["date"] = pd.to_datetime(rows.timestamp).dt.date
    rows["minute"] = (
        pd.to_datetime(rows.timestamp).dt.hour * 60 + pd.to_datetime(rows.timestamp).dt.minute
    )
    rows["true_root_cause"] = "normal"
    for event in comparable.itertuples():
        mask = (
            (rows.date == event.date)
            & (rows.equipment_id == event.equipment_id)
            & (rows.minute >= event.start_minute)
            & (rows.minute < event.end_minute)
        )
        rows.loc[mask, "true_root_cause"] = ANOMALY_TO_ROOT_CAUSE[event.anomaly_type]
    return rows


def _root_cause_report(predictions: pd.DataFrame, labels: pd.DataFrame) -> dict[str, object]:
    comparable = labels[labels.anomaly_type.isin(ANOMALY_TO_ROOT_CAUSE)]
    if comparable.empty:
        return {
            "available": False,
            "reason": "test split has no machine-level labeled anomaly events",
        }
    rows = _attach_root_cause_truth(predictions, comparable)
    labels_order = [
        "idle_waste",
        "schedule_mismatch",
        "abnormal_load",
        "equipment_inefficiency",
        "normal",
    ]
    truth = rows.true_root_cause
    predicted = rows.root_cause
    return {
        "available": True,
        "sample_count": int(len(rows)),
        "event_count": int(len(comparable)),
        "classification_report": classification_report(
            truth, predicted, labels=labels_order, output_dict=True, zero_division=0
        ),
        "confusion_matrix": confusion_matrix(truth, predicted, labels=labels_order).tolist(),
        "labels": labels_order,
    }


def run_analytics_evaluation(
    dataset_dir: str | Path,
    output_dir: str | Path,
    facility_path: str | Path = "config/facility.yaml",
    anomaly_threshold_kw: float = 35.0,
) -> dict[str, object]:
    """Run analytics baselines using train/validation for fit and test for scoring."""
    root = Path(dataset_dir)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "manifest.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    )
    if not manifest.get("synthetic", False):
        raise ValueError("evaluation requires a manifest marked synthetic=true")

    facility = load_facility(facility_path)
    parameters, _ = load_twin_config(facility_path)
    meter_train = _read_split(root, "main_meter_15min", "train")
    meter_validation = _read_split(root, "main_meter_15min", "validation")
    meter_test = _read_split(root, "main_meter_15min", "test")
    historical_meter = pd.concat([meter_train, meter_validation], ignore_index=True)
    schedule_all = pd.concat(
        [_read_split(root, "schedule", split) for split in ("train", "validation", "test")],
        ignore_index=True,
    )
    _, forecast_metrics = walk_forward_evaluate(
        historical_meter,
        meter_test,
        schedule=schedule_all,
        weather=None,
        min_train_rows=min(192, max(32, len(meter_train) // 2)),
    )
    forecast_metrics.to_csv(output / "forecast_metrics.csv", index=False)

    estimates_train = _estimates_for_split(root, "train", facility, parameters)
    estimates_validation = _estimates_for_split(root, "validation", facility, parameters)
    estimates_test = _estimates_for_split(root, "test", facility, parameters)
    residual_predictions = score_power_residuals(estimates_train, estimates_test)
    forest = fit_isolation_forest(estimates_train, seed=int(manifest.get("seed", 42)))
    forest_predictions = score_isolation_forest(forest, estimates_test)
    labels_test = _read_split(root, "anomaly_labels", "test")
    residual_metrics = event_level_metrics(labels_test, residual_predictions, interval_minutes=1)
    forest_metrics = event_level_metrics(labels_test, forest_predictions, interval_minutes=1)
    threshold_predictions = threshold_alerts(meter_test, anomaly_threshold_kw)
    threshold_metrics = event_level_metrics(labels_test, threshold_predictions, interval_minutes=15)
    residual_predictions.to_parquet(output / "residual_anomaly_scores.parquet", index=False)
    forest_predictions.to_parquet(output / "isolation_forest_scores.parquet", index=False)

    waste_predictions = classify_waste(estimates_test, schedule_all, parameters)
    root_cause_metrics = _root_cause_report(waste_predictions, labels_test)
    waste_predictions.to_parquet(output / "root_cause_predictions.parquet", index=False)
    labels_validation = _read_split(root, "anomaly_labels", "validation")
    validation_features = build_waste_features(
        estimates_validation,
        _read_split(root, "schedule", "validation"),
        parameters,
    )
    validation_labeled = _attach_root_cause_truth(validation_features, labels_validation)
    comparable_validation = labels_validation[
        labels_validation.anomaly_type.isin(ANOMALY_TO_ROOT_CAUSE)
    ]
    classifier_metrics: dict[str, object] = {
        "available": False,
        "reason": "validation split has too few labeled root-cause classes",
    }
    if not comparable_validation.empty and validation_labeled.true_root_cause.nunique() > 1:
        validation_labeled["root_cause"] = validation_labeled.true_root_cause
        classifier = fit_root_cause_classifier(validation_labeled)
        test_features = build_waste_features(estimates_test, schedule_all, parameters)
        test_labeled = _attach_root_cause_truth(test_features, labels_test)
        test_labeled["root_cause"] = test_labeled.true_root_cause
        classifier_metrics = {
            "available": True,
            "sample_count": int(len(test_labeled)),
            "event_count": int(len(labels_test)),
            **evaluate_root_cause_classifier(classifier, test_labeled),
        }

    report = {
        "synthetic": True,
        "seed": manifest.get("seed"),
        "scenario": manifest.get("scenario"),
        "split_days": manifest.get("split_days", {}),
        "forecasting": forecast_metrics.to_dict(orient="records"),
        "anomaly_detection": {
            "residual_z_score": residual_metrics,
            "isolation_forest": forest_metrics,
            "threshold_alert_baseline": threshold_metrics,
        },
        "root_cause_rules": root_cause_metrics,
        "root_cause_random_forest": classifier_metrics,
        "notes": [
            "Scores use synthetic data; evaluation labels are joined after inference.",
            "Weather is omitted because this phase does not yet generate a weather forecast.",
            "Threshold alerts are facility-wide; residual detectors score equipment rows.",
        ],
    }
    (output / "analytics_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    return report
