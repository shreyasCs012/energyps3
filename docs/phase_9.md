# Phase 9 — Held-out evaluation and deployment handoff

## Scope

Phase 9 is the final planned phase (10 phases total, numbered 0–9). It evaluates the four policy levels across scenarios S1–S4 and 20 paired synthetic seeds per scenario. P0 is the uncontrolled plant baseline, P1 is alert-only, P2 is the idle-shutdown rule, and P3 is the constrained optimizer. Each policy's commands are replayed against the ground-truth plant with isolated exogenous random streams so the baseline and controlled runs share the same seed-level disturbances.

The campaign reports means and descriptive 95% normal-approximation confidence intervals for energy, 15-minute peak demand, illustrative tariff cost, CO₂, idle waste, restarts, late jobs, comfort violations, constraint violations, and command failures. It also compares P3's checkpoint projections with full-day plant outcomes; evaluates forecasting, anomaly detection, root-cause rules and CV state classification; and runs no-CV plus controlled 100%, 92%, and 80% CV planner-input ablations on one representative day per scenario.

## Run

```sh
python -m eval.campaign --output results --scenarios S1 S2 S3 S4 --seeds 20 --optimizer-seeds 3
```

`make eval` runs the same campaign. `make eval-analytics` runs the earlier standalone analytics harness on `data/generated/`. The optimizer ensemble is set to three seeds for the campaign to bound runtime; normal optimizer runs retain the configured ensemble. Campaign data and analytics outputs are written to `results/campaign_data/` and `results/analytics/`; summary files are `results/policy_evaluation.json`, `results/policy_trials.csv`, and `reports/results.md`.

## Results

See the generated [`reports/results.md`](../reports/results.md) for policy means, paired differences, intervals, prediction errors, scenario analytics, CV confusion matrix summary, ablations, and limitations. The JSON file includes the full confusion matrix and per-trial results. All data is synthetic; utility tariff and emissions values are illustrative. The 95% intervals use a normal approximation over seed-level paired differences and are descriptive, not a formal guarantee.

## Demo and deployment

For an offline preloaded dashboard demo, install `.[dev,api,cv]`, run `python -m api.demo_cache` once, then run `python -m api.demo` from the repository root and `npm run dev` from `web/`. The API serves a synthetic S2/seed-42/day-1 dataset and starts replay at 30×. `ENERGYSENSE_DEMO_CACHE` changes the cache root; `ENERGYSENSE_DATA_DIR` and `ENERGYSENSE_REPORT_DIR` override data/report locations. `make demo-cache` and `make demo` wrap these commands where GNU Make is available.

For a hosted split-origin deployment, build the UI with `VITE_API_URL=https://<api-host>`, set `ENERGYSENSE_CORS_ORIGINS=https://<dashboard-host>` on the API, and configure the reverse proxy to forward API routes plus WebSocket upgrades for `/ws/replay`. Use persistent storage for generated data if runs must survive restarts. Configure TLS, authentication, secrets, monitoring, and process-local approval persistence in the hosting environment. The application proposes controls but does not actuate equipment.

## Verification

Phase verification commands and results are recorded in [`handoff.md`](../handoff.md). Browser-level dashboard interaction is not covered by the production bundle build; the frontend was build-verified and API behavior was covered by automated tests and local route smoke checks.

## Known scope

- Plant runs, tariffs, CV inputs, and savings are synthetic or illustrative; results must not be presented as measured savings.
- The optimizer is evaluated at 08:00, 12:00, and 16:00 rather than every five minutes. Its individual checkpoint projections can overlap, so their daily sum may not match one coherent control plan.
- Job-defer recommendations are omitted from plant commands because the command contract has no schedule-rescheduling payload.
- CV ablations quantify planner recommendation changes at one checkpoint; they do not replay each ablation as an actuator policy.
- P1 is alert-only. P2 is intentionally naive. Neither comparator is a tuned production policy.
- Forecast and anomaly results can vary by scenario; use the per-scenario reports and compare against naive baselines before selecting a model.
- This phase does not add production hosting, authentication, live utility/weather integrations, camera-specific CV calibration, or equipment actuation.
