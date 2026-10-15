"""Day-safe short-horizon meter forecasting and walk-forward evaluation."""

from collections.abc import Sequence

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

FEATURE_COLUMNS = (
    "hour",
    "day_of_week",
    "shift",
    "scheduled_job_count",
    "outdoor_temp_c",
    "lag_1",
    "lag_4",
    "lag_96",
    "rolling_mean_4",
)


def build_forecast_features(
    meter: pd.DataFrame,
    schedule: pd.DataFrame | None = None,
    weather: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build 15-minute features without future meter values.

    If ``weather`` is provided, it must contain forecast/known-ahead values, not
    observations from the held-out future.
    """
    if not {"interval_start", "main_kw"}.issubset(meter.columns):
        raise ValueError("meter must contain interval_start and main_kw")
    frame = meter.loc[:, ["interval_start", "main_kw"]].copy()
    frame["timestamp"] = pd.to_datetime(frame.pop("interval_start"))
    frame = frame.sort_values("timestamp").drop_duplicates("timestamp").set_index("timestamp")
    frame["hour"] = frame.index.hour + frame.index.minute / 60
    frame["day_of_week"] = frame.index.dayofweek
    frame["shift"] = np.select(
        [frame.index.hour < 6, frame.index.hour < 14, frame.index.hour < 22],
        [0, 1, 2],
        default=0,
    )
    frame["scheduled_job_count"] = 0.0
    if schedule is not None and not schedule.empty:
        if not {"start_ts", "end_ts"}.issubset(schedule.columns):
            raise ValueError("schedule must contain start_ts and end_ts")
        starts = pd.to_datetime(schedule.start_ts)
        ends = pd.to_datetime(schedule.end_ts)
        counts = np.zeros(len(frame), dtype=float)
        index_ns = frame.index.asi8
        for start, end in zip(starts, ends, strict=True):
            counts += (index_ns >= start.value) & (index_ns < end.value)
        frame["scheduled_job_count"] = counts
    frame["outdoor_temp_c"] = np.nan
    if weather is not None and not weather.empty:
        if not {"timestamp", "outdoor_temp_c"}.issubset(weather.columns):
            raise ValueError("weather must contain timestamp and outdoor_temp_c")
        weather_frame = weather.loc[:, ["timestamp", "outdoor_temp_c"]].copy()
        weather_frame["timestamp"] = pd.to_datetime(weather_frame.timestamp)
        weather_series = (
            weather_frame.drop_duplicates("timestamp").set_index("timestamp").outdoor_temp_c
        )
        frame["outdoor_temp_c"] = weather_series.reindex(frame.index, method="ffill")
    frame["outdoor_temp_c"] = frame.outdoor_temp_c.ffill().bfill().fillna(0.0)
    frame["lag_1"] = frame.main_kw.shift(1)
    frame["lag_4"] = frame.main_kw.shift(4)
    frame["lag_96"] = frame.main_kw.shift(96)
    frame["rolling_mean_4"] = frame.main_kw.shift(1).rolling(4, min_periods=1).mean()
    return frame.reset_index()


def _metrics(
    actual: np.ndarray, predicted: np.ndarray, lower: np.ndarray, upper: np.ndarray
) -> dict[str, float]:
    error = predicted - actual
    denominator = np.abs(actual) + np.abs(predicted)
    smape = np.divide(
        2 * np.abs(error), denominator, out=np.zeros_like(error), where=denominator > 1e-8
    )
    return {
        "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(error**2))),
        "smape": float(np.mean(smape) * 100),
        "interval_coverage": float(np.mean((actual >= lower) & (actual <= upper))),
    }


def walk_forward_evaluate(
    history: pd.DataFrame,
    evaluation: pd.DataFrame,
    schedule: pd.DataFrame | None = None,
    weather: pd.DataFrame | None = None,
    horizons_steps: Sequence[int] = (4, 8, 16, 24),
    origin_step: int = 4,
    min_train_rows: int = 192,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Evaluate horizons of 1–6 hours at expanding origins, grouped by source day.

    ``history`` must contain only earlier train/validation rows. The caller owns the
    day-level split; evaluation observations are used only for scoring and later
    origins' lag features.
    """
    if (
        origin_step < 1
        or not horizons_steps
        or any(step < 1 or step > 24 for step in horizons_steps)
    ):
        raise ValueError("origin_step must be positive and horizons must be 1–24 15-minute steps")
    combined_meter = pd.concat([history, evaluation], ignore_index=True)
    features = build_forecast_features(combined_meter, schedule, weather)
    history_times = set(pd.to_datetime(history.interval_start))
    eval_rows = features[features.timestamp.isin(pd.to_datetime(evaluation.interval_start))].copy()
    eval_rows = eval_rows.sort_values("timestamp").reset_index(drop=True)
    hist_rows = features[features.timestamp.isin(history_times)].copy()
    if len(hist_rows) < min_train_rows:
        raise ValueError(f"need at least {min_train_rows} historical meter rows")
    history_values = hist_rows.set_index("timestamp").main_kw
    all_values = features.set_index("timestamp").main_kw
    errors = (history_values - history_values.shift(96)).dropna()
    lower_offset, upper_offset = (float(errors.quantile(q)) for q in (0.1, 0.9))
    prediction_rows: list[dict[str, object]] = []

    for origin in range(0, len(eval_rows), origin_step):
        origin_time = pd.Timestamp(eval_rows.iloc[origin].timestamp)
        past = features[features.timestamp < origin_time].dropna(subset=["lag_1", "lag_4"])
        if len(past) < min_train_rows:
            continue
        model = HistGradientBoostingRegressor(max_iter=100, max_leaf_nodes=15, random_state=0)
        model.fit(past.loc[:, FEATURE_COLUMNS], past.main_kw)
        for horizon in horizons_steps:
            target_index = origin + horizon - 1
            if target_index >= len(eval_rows):
                continue
            target = eval_rows.iloc[target_index]
            timestamp = pd.Timestamp(target.timestamp)
            y = float(target.main_kw)
            seasonal_time = timestamp - pd.Timedelta(days=7)
            yesterday_time = timestamp - pd.Timedelta(days=1)
            same_day_last_week = (
                all_values.get(seasonal_time, np.nan) if seasonal_time < origin_time else np.nan
            )
            yesterday = (
                all_values.get(yesterday_time, np.nan) if yesterday_time < origin_time else np.nan
            )
            prior_four = all_values.loc[all_values.index < origin_time].tail(4)
            forecast_features = target.loc[list(FEATURE_COLUMNS)].copy()
            available = all_values.loc[all_values.index < origin_time]
            forecast_features["lag_1"] = float(available.iloc[-1])
            forecast_features["lag_4"] = float(available.iloc[-4])
            yesterday_feature_time = timestamp - pd.Timedelta(days=1)
            forecast_features["lag_96"] = (
                float(all_values.get(yesterday_feature_time))
                if yesterday_feature_time < origin_time
                and pd.notna(all_values.get(yesterday_feature_time))
                else float(available.iloc[-1])
            )
            forecast_features["rolling_mean_4"] = float(prior_four.mean())
            values = {
                "naive_yesterday": float(yesterday)
                if pd.notna(yesterday)
                else float(target.lag_96),
                "seasonal_naive": float(same_day_last_week)
                if pd.notna(same_day_last_week)
                else (float(yesterday) if pd.notna(yesterday) else float(target.lag_96)),
                "moving_average": float(prior_four.mean())
                if len(prior_four)
                else float(target.lag_1),
                "hist_gradient_boosting": float(model.predict(forecast_features.to_frame().T)[0]),
            }
            for model_name, prediction in values.items():
                prediction_rows.append(
                    {
                        "timestamp": timestamp,
                        "origin": origin_time,
                        "horizon_steps": horizon,
                        "horizon_minutes": horizon * 15,
                        "model": model_name,
                        "actual_kw": y,
                        "predicted_kw": prediction,
                        "lower_kw": max(0.0, prediction + lower_offset),
                        "upper_kw": max(0.0, prediction + upper_offset),
                    }
                )
    predictions = pd.DataFrame(prediction_rows)
    if predictions.empty:
        raise ValueError(
            "evaluation split did not produce any forecast origins with enough history"
        )
    metric_rows = []
    for (model_name, horizon), group in predictions.groupby(["model", "horizon_steps"]):
        metric_rows.append(
            {
                "model": model_name,
                "horizon_steps": int(horizon),
                "horizon_minutes": int(horizon) * 15,
                **_metrics(
                    group.actual_kw.to_numpy(),
                    group.predicted_kw.to_numpy(),
                    group.lower_kw.to_numpy(),
                    group.upper_kw.to_numpy(),
                ),
            }
        )
    return predictions, pd.DataFrame(metric_rows).sort_values(["horizon_steps", "model"])
