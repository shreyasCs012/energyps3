# EnergySense Twin handoff

## Current state

Phases 0 through 3 are implemented. This remains a synthetic-data prototype; no real facility data or validated savings claims are included.

## Work completed

- Added Python package metadata, lint/test settings, Makefile targets, CI workflow, and `.gitignore`.
- Added Pydantic contracts and JSON Schema/TypeScript export.
- Added baseline configuration for the one-bay facility, tariffs, scenarios, CV, optimizer, and Phase 2 policies.
- Added a minimal React/Vite shell and project status documentation.
- Added the seeded ground-truth plant, state machine, daily schedule and weather generation, anomaly injection/labels, and Parquet dataset writer.
- Added the separate observable-input twin estimator, snapshot builder, least-squares machine/thermal calibration, simplified simulation, ensemble and common-random-number what-if interfaces, plus P0–P2 policies.
- Added day-safe 15-minute forecasting and naive/seasonal/moving-average baselines, IsolationForest and state-conditional residual anomaly scoring, a threshold-alert comparator, waste/root-cause rules and RandomForest classifier.
- Added a train/evaluation CLI that writes model artifacts and test-split reports, plus Phase 3 coverage in `docs/phase_3.md`.
- Captured assumptions in `ASSUMPTIONS.md`; phase records are in `docs/phase_0.md` through `docs/phase_3.md`.

## Verification and commits

- Phase 0: `python -m pytest` (4 passed), Ruff, schema export, YAML parsing, and `npm run build` in `web/` passed.
- Phase 1: `python -m pytest` (10 passed), Ruff, and two-day simulated-CV Parquet smoke generation passed.
- Phase 2: `python -m pytest` (15 passed), `python -m ruff check .`, `python -m ruff format --check .`, and `git diff --check` passed.
- Phase 3: `python -m pytest` (20 passed), `python -m ruff check .`, `python -m ruff format --check .`, and `git diff --check` passed. Generated 5-day and 10-day Parquet smoke runs exercised report generation; training saved a serialized IsolationForest artifact.
- GNU Make is not installed in the Windows environment, so Makefile targets were verified using their underlying commands.
- Phase commits are pushed to `origin/main`: `4523d22 chore: scaffold EnergySense Twin project`, `7644918 feat: add seeded plant simulator and data generation`, `b287742 feat: add calibrated digital twin and baseline policies`, and Phase 3 `feat: add forecasting anomaly detection and evaluation harness`.

## Local run and deployment steps

No production deployment is available at this checkpoint. For local synthetic generation and checks on a machine with Python 3.11+:

1. Clone the repository and enter its root.
2. Run `python -m pip install -e ".[dev]"` to install the simulator, PyArrow, scikit-learn, tests, and lint dependencies.
3. Run `python -m plant.generate --scenario S1 --seed 42` to generate the 70-day synthetic Parquet dataset under `data/generated/`.
4. Run `python -m pytest` and `python -m ruff check .` to verify the current implementation.
5. Run `python -m analytics.train --input data/generated --output models/analytics.joblib` to fit the normal-day anomaly model.
6. Run `python -m eval.run --input data/generated --output reports/analytics` to produce the forecasting, event-level anomaly, and root-cause report artifacts.
7. Run `python -m pytest` and `python -m ruff check .` for final checks.

`make data`, `make train`, and `make eval` invoke these steps where GNU Make is installed. `make demo` remains a future-phase target. There is no production hosting configuration, API, database, or real-facility integration yet. Final deployment steps must be updated after the API and dashboard phases.

## Known Phase 2 limits

The twin is simplified and uses synthetic telemetry. P2 is intentionally the naive idle-duration shutdown policy; break-even, dependency, warm-up, and minimum on/off constraints belong to the optimizer phase. The analytics smoke run shows that baseline models can outperform the learned forecast at some horizons and that anomaly/root-cause rules miss labeled events. The report keeps those results visible. Forecast weather is omitted until forecast inputs are modeled.

## Next phase

Phase 4: implement video CV, procedural rendering, clip ingestion, and replay while keeping train/validation/test splits grouped by source clip.
