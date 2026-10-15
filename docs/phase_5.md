# Phase 5 — Optimizer and recommendations

## Built

- Added rolling-horizon recommendation planning using the production schedule and forecast scenario over the configured four-hour window.
- Added deterministic candidate generation for machine standby, pre-warm, zone lighting shutoff, HVAC setback, and flexible-job deferral.
- Evaluated candidate actions with paired seeded twin runs, including machine-state confidence and weather forecast perturbations. Recommendation KPI values are baseline-minus-action deltas; positive values indicate improvement.
- Added hard checks for machine minimum on/off time, idle-gap break-even including restart energy, compressor dependency, critical jobs, job release/due windows, machine exclusivity, occupied comfort, optional peak cap, and concurrent startups.
- Added a deterministic 15-minute feasible-slot search for flexible-job shifting and greedy selection by objective improvement per action minute. OR-Tools is not required.
- Added Pydantic recommendation contracts, JSON Schema and TypeScript exports, action parameters, confidence intervals, constraints, evidence references, and revert conditions.
- Added `python -m policies.optimize` and `make optimize`. They estimate the current state from observable input fields, write recommendations to JSON, and do not send controls to the plant.

## How to run

Install project dependencies and generate data first:

```sh
python -m pip install -e ".[dev,api,cv]"
python -m plant.generate --scenario S1 --seed 42
python -m policies.optimize --input data/generated \
  --timestamp 2025-01-01T08:00:00+05:30 \
  --output reports/optimizer/recommendations.json --mode human
```

The optimizer uses `config/optimizer.yaml` for horizon, replanning interval, ensemble size, startup limit, optional peak cap, CO2 and lateness weights, and HVAC setback. Use `--mode auto` to label an output plan for evaluation; it still only returns recommendations and never actuates equipment.

The CLI reads the generated telemetry, meter, HVAC, schedule, and CV Parquet files. State estimation explicitly selects observable columns, while snapshot construction uses only observations available at the requested timestamp. The JSON file marks its dataset synthetic and includes accepted recommendations plus rejected candidates and reasons.

## Verification

- `python -m pytest -q`: 37 passed.
- `python -m ruff check .`: passed.
- `python -m ruff format --check .`: 58 files already formatted.
- `git diff --check`: passed.
- Generated a one-day S1 synthetic dataset, then ran the optimizer CLI at 08:00 using the configured 30-seed ensemble, followed by a fast two-seed smoke after final edits. Both JSON outputs contained accepted and rejected candidates, per-rule constraint results, projection intervals, meter windows, and matching CV event IDs.
- The full suite reports one benign Windows `joblib` physical-core detection warning; it falls back to logical cores.

## Known gaps

- Recommendations are not applied to the plant, and no human apply/reject/schedule workflow exists yet. The human/auto mode is metadata for downstream evaluation and UI integration.
- The job-shift fallback searches later 15-minute starts and approximates the search objective with the twin; it is not a global CP-SAT schedule solver and does not model job precedence absent from the schedule.
- Savings and objective weights rely on the configured synthetic tariff and assumptions. This phase does not establish real-facility savings or safety certification.
- Flexible-job deferral, peak-cap behavior, and state uncertainty need broader scenario evaluation in Phase 9. The default peak cap is unset.
- State-age estimates assume minute-cadence observations; gaps in field telemetry need explicit handling before production use.
