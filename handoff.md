# EnergySense Twin handoff

## Current state

Phases 0 through 6 are implemented. This remains a synthetic-data prototype; no real facility data or validated savings claims are included.

## Work completed

- Added Python package metadata, lint/test settings, Makefile targets, CI workflow, and `.gitignore`.
- Added Pydantic contracts and JSON Schema/TypeScript export.
- Added baseline configuration for the one-bay facility, tariffs, scenarios, CV, optimizer, and Phase 2 policies.
- Added a minimal React/Vite shell and project status documentation.
- Added the seeded ground-truth plant, state machine, daily schedule and weather generation, anomaly injection/labels, and Parquet dataset writer.
- Added the separate observable-input twin estimator, snapshot builder, least-squares machine/thermal calibration, simplified simulation, ensemble and common-random-number what-if interfaces, plus P0–P2 policies.
- Added day-safe 15-minute forecasting and naive/seasonal/moving-average baselines, IsolationForest and state-conditional residual anomaly scoring, a threshold-alert comparator, waste/root-cause rules and RandomForest classifier.
- Added a train/evaluation CLI that writes model artifacts and test-split reports, plus Phase 3 coverage in `docs/phase_3.md`.
- Added a 960×540 procedural top-down renderer with video and frame-label output; streaming video decode, common clip normalization, ROI motion/HSV/brightness features, temporal hysteresis, rule and RandomForest machine state classification, zone light detection, and YOLO/HOG people detection.
- Added source-clip manifest validation and splitting, deterministic training-only appearance augmentation, held-out CV reports, and state-matched replay clip offsets with renderer fallback.
- Added constraint-checked rolling-horizon recommendations for machine standby, pre-warm, zone lights, HVAC setback, and flexible job shifting. Candidates are evaluated with paired seeded twin projections and include confidence intervals, checks, evidence, and revert conditions.
- Added Phase 5 recommendation contracts, generated schemas and TypeScript types, and an optimizer CLI/Makefile target.
- Added Phase 6 grounded template and optional LLM recommendation explanations, numeric validation with safe template fallback, allowlisted copilot tool routing with an offline regex path, results JSON to Markdown report generation, contracts, schemas, TypeScript types, and Makefile targets.
- Captured assumptions in `ASSUMPTIONS.md`; phase records are in `docs/phase_0.md` through `docs/phase_6.md`.

## Verification and commits

- Phase 0: `python -m pytest` (4 passed), Ruff, schema export, YAML parsing, and `npm run build` in `web/` passed.
- Phase 1: `python -m pytest` (10 passed), Ruff, and two-day simulated-CV Parquet smoke generation passed.
- Phase 2: `python -m pytest` (15 passed), `python -m ruff check .`, `python -m ruff format --check .`, and `git diff --check` passed.
- Phase 3: `python -m pytest` (20 passed), `python -m ruff check .`, `python -m ruff format --check .`, and `git diff --check` passed. Generated 5-day and 10-day Parquet smoke runs exercised report generation; training saved a serialized IsolationForest artifact.
- Phase 4: `python -m pytest -q` (28 passed), `python -m ruff check .`, `python -m ruff format --check .` (54 files formatted), `git diff --check`, and one-minute renderer MP4/CSV smoke generation passed. Pytest reports one benign Windows `joblib` physical-core detection warning and falls back to logical cores.
- Phase 5: `python -m pytest -q` (37 passed), `python -m ruff check .`, `python -m ruff format --check .` (58 files formatted), and `git diff --check` passed. Generated one synthetic day and ran `python -m policies.optimize` at 08:00 with the 30-seed ensemble plus a fast two-seed smoke after final edits; recommendation JSON included accepted/rejected candidates, KPI deltas, intervals, rule checks, meter windows, and CV event references. Same benign Windows `joblib` warning.
- Phase 6: `python -m pytest -q` (47 passed, one benign Windows `joblib` warning), `python -m ruff check .`, `python -m ruff format --check .` (68 files formatted), `python -m contracts.export_schema`, `git diff --check`, and an end-to-end optimizer → explanation → Markdown report smoke run passed. The optional live LLM provider was not called. Feature commit: `1ee2974 feat: add grounded GenAI explanations and copilot`.
- GNU Make is not installed in the Windows environment, so Makefile targets were verified using their underlying commands.
- Phase commits are pushed to `origin/main`: `4523d22 chore: scaffold EnergySense Twin project`, `7644918 feat: add seeded plant simulator and data generation`, `b287742 feat: add calibrated digital twin and baseline policies`, `47f3c14 feat: add forecasting anomaly detection and evaluation harness`, `11daab6 feat: add streaming CV and procedural replay pipeline`, `a8175d9 feat: add constrained optimizer recommendations`, and Phase 6 `1ee2974 feat: add grounded GenAI explanations and copilot`.

## Local run and deployment steps

No production deployment is available at this checkpoint. For local synthetic generation and checks on a machine with Python 3.11+:

1. Clone the repository and enter its root.
2. Run `python -m pip install -e ".[dev,api,cv]"` to install the simulator, scikit-learn, Pillow, PyAV, OpenCV HOG, tests, and lint dependencies.
3. Run `python -m plant.generate --scenario S1 --seed 42` to generate the 70-day synthetic Parquet dataset under `data/generated/`.
4. Run `python -m pytest` and `python -m ruff check .` to verify the current implementation.
5. Run `python -m analytics.train --input data/generated --output models/analytics.joblib` to fit the normal-day anomaly model.
6. Run `python -m eval.run --input data/generated --output reports/analytics` to produce the forecasting, event-level anomaly, and root-cause report artifacts.
7. Run `python -m policies.optimize --input data/generated --timestamp 2025-01-01T08:00:00+05:30 --output reports/optimizer/recommendations.json --mode human` to produce a recommendation plan from observable input files. Use `--mode auto` for evaluation metadata; the command still does not actuate controls.
8. Run `python -m genai.cli --input reports/optimizer/recommendations.json --output reports/optimizer/explanations.json` for grounded explanations. The deterministic template works offline. Optional LLM use requires `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_API_BASE_URL`, and `LLM_MODEL` environment variables.
9. Run `python -m genai.report reports/analytics/analytics_report.json --output reports/end_of_day.md` to render a Markdown summary from the results JSON.
10. Run `python -m renderer.generate --minutes 10 --video data/generated/renderer/synthetic.mp4 --labels data/generated/renderer/labels.csv` to render a small labeled sample.
11. Populate `data/clips/manifest.csv` with at least three clips and the documented columns, then run `python -m cv.ingest_clips --manifest data/clips/manifest.csv` to normalize clips and emit event Parquet.
12. Run `python -m pytest` and `python -m ruff check .` for final checks.

`make data`, `make train`, `make eval`, `make optimize`, `make explain`, `make report`, `make render`, and `make cv` invoke these steps where GNU Make is installed. `make cv` requires at least three videos listed in the clip manifest. `make optimize` reads generated one-minute telemetry, 15-minute meter data, HVAC, schedule, and CV events; it writes only a recommendation JSON file. `make explain` uses deterministic local templates unless optional provider variables are configured. `make demo` remains a future-phase target. There is no production hosting configuration, API, database, control actuation, or real-facility integration yet. Final deployment steps must be updated after the API and dashboard phases.

## Known limitations

The twin is simplified and uses synthetic telemetry. P2 remains a naive idle-duration shutdown baseline; Phase 5 checks break-even, dependencies, warm-up, and minimum on/off timing before recommending actions. The analytics smoke run shows that baseline models can outperform the learned forecast at some horizons and that anomaly/root-cause rules miss labeled events. CV state classification is a heuristic prototype and needs clip-specific evaluation/calibration. The optimizer's solver-free job shifting uses a 15-minute feasible-slot search rather than CP-SAT and requires broader scenario evaluation. Forecast weather is represented by configured forecast perturbations, not a live forecast feed. There are no real or AI-generated clips in the repository, production CV ROIs require camera-specific calibration, and replay currently returns clip offsets/crossfade metadata for a later UI/API to composite.

## Next phase

Phase 7: add REST and WebSocket API endpoints and wire copilot tools to the twin and analytics services. This is Phase 7 of 10 total phases (numbered 0–9).
