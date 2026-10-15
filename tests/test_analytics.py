from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from analytics.anomaly import (
    event_level_metrics,
    fit_isolation_forest,
    score_isolation_forest,
    score_power_residuals,
    threshold_alerts,
)
from analytics.forecast import build_forecast_features, walk_forward_evaluate
from analytics.waste import (
    build_waste_features,
    classify_waste,
    evaluate_root_cause_classifier,
    fit_root_cause_classifier,
)
from twin.model import MachineParameters


def test_forecast_features_and_walk_forward_metrics_are_day_ordered():
    start = pd.Timestamp("2025-01-01", tz="UTC")
    meter = pd.DataFrame(
        {
            "interval_start": pd.date_range(start, periods=12 * 96, freq="15min"),
            "main_kw": 20 + np.sin(np.arange(12 * 96) / 8),
        }
    )
    features = build_forecast_features(meter)
    assert features.loc[100, "lag_1"] == meter.loc[99, "main_kw"]
    history = meter.iloc[: 10 * 96]
    evaluation = meter.iloc[10 * 96 :]
    predictions, metrics = walk_forward_evaluate(
        history,
        evaluation,
        horizons_steps=(4, 8, 24),
        origin_step=24,
        min_train_rows=192,
    )
    assert set(predictions.model) == {
        "naive_yesterday",
        "seasonal_naive",
        "moving_average",
        "hist_gradient_boosting",
    }
    assert set(metrics.horizon_minutes) == {60, 120, 360}
    assert metrics.mae.notna().all() and metrics.interval_coverage.between(0, 1).all()


def test_residual_and_isolation_forest_scores_use_normal_training():
    timestamps = pd.date_range("2025-01-01", periods=120, freq="min", tz="UTC")
    normal = pd.DataFrame(
        {
            "timestamp": timestamps,
            "equipment_id": ["M1"] * len(timestamps),
            "state": ["RUNNING"] * len(timestamps),
            "power_kw_estimate": [5.0 + (index % 5) * 0.01 for index in range(len(timestamps))],
        }
    )
    evaluation = normal.iloc[:20].copy()
    evaluation.loc[evaluation.index[-1], "power_kw_estimate"] = 9.0
    residuals = score_power_residuals(normal, evaluation, z_threshold=3)
    assert residuals.iloc[-1].is_anomaly
    model = fit_isolation_forest(normal, seed=12)
    first = score_isolation_forest(model, evaluation)
    second = score_isolation_forest(model, evaluation)
    pd.testing.assert_series_equal(first.anomaly_score, second.anomaly_score)


def test_event_metrics_and_threshold_alert_baseline():
    start = datetime(2025, 1, 2, tzinfo=UTC)
    labels = pd.DataFrame(
        [
            {
                "event_id": "e1",
                "date": "2025-01-02",
                "anomaly_type": "bearing_degradation",
                "equipment_id": "M1",
                "start_minute": 10,
                "end_minute": 20,
            }
        ]
    )
    predictions = pd.DataFrame(
        {
            "timestamp": [start + timedelta(minutes=index) for index in (12, 30)],
            "equipment_id": ["M1", "M1"],
            "is_anomaly": [True, True],
        }
    )
    metrics = event_level_metrics(labels, predictions)
    assert metrics["detected_events"] == 1
    assert metrics["detection_delay_min"] == 2
    assert metrics["false_alerts"] == 1
    meter = pd.DataFrame({"interval_start": [start], "main_kw": [40.0]})
    assert threshold_alerts(meter, 35).is_anomaly.iloc[0]


def test_idle_waste_rule_requires_sustained_idle_and_no_nearby_job():
    timestamp = pd.date_range("2025-01-01 22:00", periods=30, freq="min", tz="UTC")
    estimates = pd.DataFrame(
        {
            "timestamp": timestamp,
            "equipment_id": ["M1"] * len(timestamp),
            "state": ["IDLE"] * len(timestamp),
            "power_kw_estimate": [2.2] * len(timestamp),
        }
    )
    parameters = {"M1": MachineParameters("M1", 6.5, 2.2, 0.4, 8, 0.6, 10, 5, submetered=True)}
    result = classify_waste(estimates, pd.DataFrame(), parameters)
    assert result.root_cause.iloc[:10].eq("normal").all()
    assert result.root_cause.iloc[10:].eq("idle_waste").all()


def test_waste_features_vectorize_schedule_windows_and_idle_runs():
    timestamp = pd.date_range("2025-01-01 08:00", periods=6, freq="min", tz="UTC")
    estimates = pd.DataFrame(
        {
            "timestamp": timestamp,
            "equipment_id": ["M1"] * len(timestamp),
            "state": ["IDLE", "IDLE", "OFF", "IDLE", "IDLE", "IDLE"],
            "power_kw_estimate": [2.0] * len(timestamp),
        }
    )
    schedule = pd.DataFrame(
        [
            {
                "start_ts": timestamp[2],
                "end_ts": timestamp[4],
                "required_machines": "M1",
            }
        ]
    )
    parameters = {"M1": MachineParameters("M1", 6.5, 2.2, 0.4, 8, 0.6, 10, 5)}
    features = build_waste_features(estimates, schedule, parameters)
    assert features.scheduled_active.tolist() == [False, False, True, True, False, False]
    assert features.scheduled_use_next_min.tolist() == [2.0, 1.0, 0.0, np.inf, np.inf, np.inf]
    assert features.idle_duration_min.tolist() == [1, 2, 0, 1, 2, 3]


def test_root_cause_random_forest_handles_unbounded_schedule_gap_feature():
    rows = []
    causes = ["normal", "idle_waste", "abnormal_load", "equipment_inefficiency"]
    for index in range(80):
        cause = causes[index % len(causes)]
        rows.append(
            {
                "power_kw_estimate": float(index % 9),
                "p_standby_kw": 0.4,
                "idle_duration_min": index % 30,
                "scheduled_active": bool(index % 2),
                "scheduled_use_next_min": np.inf if index % 3 else 30.0,
                "residual_z": float(index % 4),
                "root_cause": cause,
            }
        )
    labeled = pd.DataFrame(rows)
    model = fit_root_cause_classifier(labeled, seed=7)
    report = evaluate_root_cause_classifier(model, labeled)
    assert set(report["labels"]) == set(causes) | {"schedule_mismatch"}
    assert "classification_report" in report and "confusion_matrix" in report
