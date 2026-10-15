# Phase 3 — Analytics and evaluation harness

## Built

- Added 15-minute meter features and expanding walk-forward forecasts at horizons from 1 to 6 hours. Models include yesterday's same-time naive forecast, seasonal naive, moving average, and scikit-learn histogram gradient boosting. Reports include MAE, RMSE, sMAPE, and empirical interval coverage.
- Added state-conditional equipment power residual z-scores, a normal-training-only IsolationForest, and the P1 main-meter threshold-alert baseline.
- Added event-level precision, recall, F1, per-anomaly-type recall, and detection delay. Evaluation labels are joined after inference.
- Added root-cause rules for idle waste, schedule mismatch, abnormal load, and equipment inefficiency, plus a RandomForest trained from labeled validation days and scored on held-out test days.
- Added `analytics.train` to persist a normal-day IsolationForest artifact and `eval.run` to produce metrics and scored Parquet outputs.
- Updated `make train` and `make eval`; generated model/report artifacts are ignored by Git.

## How to run

With a generated dataset and development dependencies installed:

```sh
python -m analytics.train --input data/generated --output models/analytics.joblib
python -m eval.run --input data/generated --output reports/analytics
```

The evaluation writes `analytics_report.json`, `forecast_metrics.csv`, and Parquet scores for residual anomalies, IsolationForest anomalies, and root-cause predictions. To generate the configured dataset first, run `python -m plant.generate --scenario S1 --seed 42`.

## Verification

- The full `pytest` suite passed (20 tests); Phase 3 includes walk-forward forecast, anomaly scoring, threshold baseline, event metric, root-cause rule, and RandomForest tests.
- `python -m ruff check .`, `python -m ruff format --check .`, and `git diff --check` passed.
- Generated 5-day and 10-day S1 datasets exercised the full evaluation report path; normal-day model training produced a serialized artifact.
- Smoke evaluation showed no consistent learned-model win: yesterday's baseline outperformed histogram gradient boosting at longer horizons. Anomaly and root-cause reports also exposed missed labels and false alerts, as intended by the honest evaluation requirement.

## Known gaps

- Forecast weather is omitted because the repository does not yet generate weather forecast inputs; future schedule data is treated as known.
- Evaluation is a single configured scenario/seed, not the full S1–S4 by N-seed evaluation matrix from Phase 9.
- On this Windows host, scikit-learn emits a harmless joblib warning because it cannot query physical cores; it falls back to the detected logical core count. Set `LOKY_MAX_CPU_COUNT` to suppress the warning if desired.
- The synthetic anomaly labels cover selected intervals and do not represent every source of abnormal load. The five-class RandomForest can lack train examples for some classes; per-class support and failures remain in its report.
- The baseline threshold is configurable but currently a fixed default, not calibrated on validation data. No real facility validation, video CV, optimizer policy comparison, or predicted-versus-realized plant metrics are implemented.
