# EnergySense Twin handoff

## Current state

Phases 0 through 9 are implemented; Phase 9 is the final planned phase. This remains a synthetic-data prototype; no real facility data or validated savings claims are included.

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
- Added Phase 7 FastAPI REST endpoints for scenarios, runs, KPIs, recommendation decisions, what-if, forecast, anomaly alerts, CV events, reports, and copilot. Added a controllable WebSocket replay for estimated twin state, meter and CV events, recommendations, speed, pause, seek, policy, and scenario selection.
- Added Phase 8 responsive React control-room dashboard views for live floor/replay, twin comparison, recommendation review, analytics, impact report, and copilot. Wired the UI to REST/WebSocket routes, exposed configured tariff assumptions, added a Vite development proxy, and added an environment-configured CORS origin allowlist for separate-origin deployments.
- Added Phase 9 paired ground-truth command replay with common random numbers, P0–P3 policy comparisons across held-out scenarios, per-trial and paired confidence summaries, predicted-versus-realized reporting, analytics baselines, CV confusion matrices, and controlled no-CV/100%/92%/80% planner-input ablations. Added a preloaded S2 demo cache and 30× replay default. Root-cause feature generation now vectorizes per-machine schedule windows to support campaign-scale evaluation.
- Captured assumptions in `ASSUMPTIONS.md`; phase records are in `docs/phase_0.md` through `docs/phase_8.md`.

## Verification and commits

- Phase 0: `python -m pytest` (4 passed), Ruff, schema export, YAML parsing, and `npm run build` in `web/` passed.
- Phase 1: `python -m pytest` (10 passed), Ruff, and two-day simulated-CV Parquet smoke generation passed.
- Phase 2: `python -m pytest` (15 passed), `python -m ruff check .`, `python -m ruff format --check .`, and `git diff --check` passed.
- Phase 3: `python -m pytest` (20 passed), `python -m ruff check .`, `python -m ruff format --check .`, and `git diff --check` passed. Generated 5-day and 10-day Parquet smoke runs exercised report generation; training saved a serialized IsolationForest artifact.
- Phase 4: `python -m pytest -q` (28 passed), `python -m ruff check .`, `python -m ruff format --check .` (54 files formatted), `git diff --check`, and one-minute renderer MP4/CSV smoke generation passed. Pytest reports one benign Windows `joblib` physical-core detection warning and falls back to logical cores.
- Phase 5: `python -m pytest -q` (37 passed), `python -m ruff check .`, `python -m ruff format --check .` (58 files formatted), and `git diff --check` passed. Generated one synthetic day and ran `python -m policies.optimize` at 08:00 with the 30-seed ensemble plus a fast two-seed smoke after final edits; recommendation JSON included accepted/rejected candidates, KPI deltas, intervals, rule checks, meter windows, and CV event references. Same benign Windows `joblib` warning.
- Phase 6: `python -m pytest -q` (47 passed, one benign Windows `joblib` warning), `python -m ruff check .`, `python -m ruff format --check .` (68 files formatted), `python -m contracts.export_schema`, `git diff --check`, and an end-to-end optimizer → explanation → Markdown report smoke run passed. The optional live LLM provider was not called. Feature commit: `1ee2974 feat: add grounded GenAI explanations and copilot`.
- Phase 7: `python -m pytest -q` (53 passed; Starlette TestClient/httpx deprecation and benign Windows `joblib` warnings), `python -m ruff check .`, `python -m ruff format --check .` (72 files formatted), `python -m contracts.export_schema`, `git diff --check`, and `npm run build` in `web/` passed. API tests cover REST contracts, run/what-if, copilot, reports, proposal decisions, validation errors, and WebSocket pause/seek/replay. Feature commit: `01a7631 feat: add EnergySense REST and replay API`.
- Phase 8: `npm run build` in `web/` passed; `python -m pytest -q` (53 passed, including the CORS origin assertion, with the same two environment/library warnings), `python -m ruff check .`, `python -m ruff format --check .` (73 files), and `git diff --check` passed. Local API smoke generated S2 / seed 42 / one synthetic day and successfully queried KPIs, a four-point forecast, and Markdown report. The temporary Vite port was not reachable from the browser harness, so UI interaction was not browser-verified. Vite notes the minified JS chunk exceeds 500 kB.
- Phase 9: Full campaign completed in 602.65 seconds: 320 paired policy trials (S1–S4 × 20 seeds × P0–P3), four scenario analytics evaluations, 576,000 simulated CV state observations, policy KPI means/paired 95% confidence intervals, forecast/anomaly/root-cause baselines, predicted-versus-realized comparison, and no-CV/100%/92%/80% planner-input ablations. `python -m pytest -q` (57 passed, with the same Starlette/httpx and Windows joblib warnings), `ruff check .`, `ruff format --check .` (79 files), `git diff --check`, and `npm run build` passed. `python -m api.demo_cache` precomputed S2 / seed 42 / one simulated day; direct service smoke served cached KPIs, recommendations, forecast, CV events, and report. The browser harness still could not reach the temporary Vite port; frontend verification is the production build.
- GNU Make is not installed in the Windows environment, so Makefile targets were verified using their underlying commands.
- Phase commits are pushed to `origin/main`: `4523d22 chore: scaffold EnergySense Twin project`, `7644918 feat: add seeded plant simulator and data generation`, `b287742 feat: add calibrated digital twin and baseline policies`, `47f3c14 feat: add forecasting anomaly detection and evaluation harness`, `11daab6 feat: add streaming CV and procedural replay pipeline`, `a8175d9 feat: add constrained optimizer recommendations`, Phase 6 `1ee2974 feat: add grounded GenAI explanations and copilot`, and Phase 7 `01a7631 feat: add EnergySense REST and replay API`.

## Phase commits

Phase 0–7 feature commits are pushed to `origin/main`: `4523d22 chore: scaffold EnergySense Twin project`, `7644918 feat: add seeded plant simulator and data generation`, `b287742 feat: add calibrated digital twin and baseline policies`, `47f3c14 feat: add forecasting anomaly detection and evaluation harness`, `11daab6 feat: add streaming CV and procedural replay pipeline`, `a8175d9 feat: add constrained optimizer recommendations`, `1ee2974 feat: add grounded GenAI explanations and copilot`, and `01a7631 feat: add EnergySense REST and replay API`. Phase 8 commits: `da115ec feat: build EnergySense control room dashboard`, `8c9f9fc feat: configure dashboard API deployment origins`, `9b698ae docs: record Phase 8 dashboard checkpoint`, and `a81798c docs: clarify Phase 8 deployment handoff`. Phase 9 implementation commits: `58b39a4 feat: run paired Phase 9 policy evaluation` and `62b2fd2 fix: write Phase 9 artifacts with LF endings`. `reports/results.md`, the JSON/CSV campaign outputs, and this handoff are committed and pushed on `origin/main`; use `git log` for the documentation commit ID.

## Local run and deployment steps

No production deployment is available at this checkpoint. For local synthetic generation and checks on a machine with Python 3.11+ and Node.js/npm:

1. Clone the repository and enter its root.
2. Run `python -m pip install -e ".[dev,api,cv]"` to install the simulator, API, tests, and lint dependencies.
3. For the preloaded offline demo, run `python -m api.demo_cache` once (or `make demo-cache`) to generate the synthetic S2/seed-42 cache, then run `python -m api.demo` (or `make demo`) and open `http://127.0.0.1:8000/docs`. The UI replay starts at 30×. To launch an empty API without preloading, use `uvicorn api.app:app --host 127.0.0.1 --port 8000`.
4. In another terminal, run `cd web`, `npm install`, and `npm run dev`; open the Vite URL (normally `http://localhost:5173`). Its development proxy forwards REST and WebSocket requests to the API.
5. Select a scenario and click **Run simulation**. The dashboard calls `POST /run` to create a one-day synthetic dataset. Set `ENERGYSENSE_DATA_DIR` and `ENERGYSENSE_REPORT_DIR` to change data/report locations.
6. Run `python -m plant.generate --scenario S1 --seed 42` to generate the configured 70-day synthetic Parquet dataset under `data/generated/` when full analytics are needed. Run `python -m eval.campaign --output results --scenarios S1 S2 S3 S4 --seeds 20 --optimizer-seeds 3` (or `make eval`) for the final paired policy campaign. The earlier analytics-only runner remains available as `make eval-analytics`.
7. Run `python -m pytest` and `python -m ruff check .` to verify the current implementation.
8. Run `python -m analytics.train --input data/generated --output models/analytics.joblib` to fit the normal-day anomaly model.
9. Run `python -m eval.run --input data/generated --output reports/analytics` to produce forecasting, event-level anomaly, and root-cause report artifacts.
10. Run `python -m policies.optimize --input data/generated --timestamp 2025-01-01T08:00:00+05:30 --output reports/optimizer/recommendations.json --mode human` to produce a recommendation plan from observable input files. It does not actuate controls.
11. Run `python -m genai.cli --input reports/optimizer/recommendations.json --output reports/optimizer/explanations.json` for grounded explanations. The deterministic template works offline. Optional LLM use requires `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_API_BASE_URL`, and `LLM_MODEL` environment variables.
12. Run `python -m genai.report reports/analytics/analytics_report.json --output reports/end_of_day.md` to render a Markdown summary from results JSON.
13. Run `python -m renderer.generate --minutes 10 --video data/generated/renderer/synthetic.mp4 --labels data/generated/renderer/labels.csv` to render a small labeled sample.
14. Populate `data/clips/manifest.csv` with at least three videos and the documented columns, then run `python -m cv.ingest_clips --manifest data/clips/manifest.csv` to normalize clips and emit event Parquet.
15. Run `python -m pytest`, `python -m ruff check .`, and `cd web && npm run build` for final checks.

`make data`, `make train`, `make eval`, `make optimize`, `make explain`, `make report`, `make render`, and `make cv` invoke these steps where GNU Make is installed. `make cv` requires at least three videos listed in the clip manifest. For a separate-origin deployment, build with `VITE_API_URL=https://<api-host>` and set `ENERGYSENSE_CORS_ORIGINS=https://<dashboard-host>` on the API; configure the HTTPS reverse proxy to forward `/ws/replay` WebSocket upgrades. Keep generated data on persistent storage if runs must survive restarts. Production hosting, TLS certificates, authentication, and operations still need configuration. Recommendation decisions are process-local proposals and no control actuation is configured.

## Known limitations

The twin is simplified and uses synthetic telemetry. P2 remains a naive idle-duration shutdown baseline; Phase 5 checks break-even, dependencies, warm-up, and minimum on/off timing before recommending actions. The analytics smoke run shows that baseline models can outperform the learned forecast at some horizons and that anomaly/root-cause rules miss labeled events. The API serves an explicitly labeled moving-average forecast and threshold anomaly baseline; decisions are process-local and non-actuating. CV state classification is a heuristic prototype and needs clip-specific evaluation/calibration. The optimizer's solver-free job shifting uses a 15-minute feasible-slot search rather than CP-SAT and requires broader scenario evaluation. Forecast weather is represented by configured forecast perturbations, not a live forecast feed. There are no real or AI-generated clips in the repository, production CV ROIs require camera-specific calibration, and replay streams estimated state and events without video compositing.

## Final phase status

Phase 9 is the final planned phase; the project has 10 total phases, numbered 0–9. The final campaign metrics, ablations, limitations, and deployment guidance are recorded in [docs/phase_9.md](docs/phase_9.md) and [reports/results.md](reports/results.md). Exact Phase 9 verification results and commit IDs are listed below.
