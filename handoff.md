# EnergySense Twin handoff

## Current state

Phases 0, 1, and 2 are implemented. This remains a synthetic-data prototype; no real facility data or validated savings claims are included.

## Work completed

- Added Python package metadata, lint/test settings, Makefile targets, CI workflow, and `.gitignore`.
- Added Pydantic contracts and JSON Schema/TypeScript export.
- Added baseline configuration for the one-bay facility, tariffs, scenarios, CV, optimizer, and Phase 2 policies.
- Added a minimal React/Vite shell and project status documentation.
- Added the seeded ground-truth plant, state machine, daily schedule and weather generation, anomaly injection/labels, and Parquet dataset writer.
- Added the separate observable-input twin estimator, snapshot builder, least-squares machine/thermal calibration, simplified simulation, ensemble and common-random-number what-if interfaces, plus P0–P2 policies.
- Captured assumptions in `ASSUMPTIONS.md`; phase records are in `docs/phase_0.md`, `docs/phase_1.md`, and `docs/phase_2.md`.

## Verification and commits

- Phase 0: `python -m pytest` (4 passed), Ruff, schema export, YAML parsing, and `npm run build` in `web/` passed.
- Phase 1: `python -m pytest` (10 passed), Ruff, and two-day simulated-CV Parquet smoke generation passed.
- Phase 2: `python -m pytest` (15 passed), `python -m ruff check .`, `python -m ruff format --check .`, and `git diff --check` passed.
- GNU Make is not installed in the Windows environment, so Makefile targets were verified using their underlying commands.
- Phase commits are pushed to `origin/main`: `chore: scaffold EnergySense Twin project`, `feat: add seeded plant simulator and data generation`, and the Phase 2 commit recorded in Git history.

## Local run and deployment steps

No production deployment is available at this checkpoint. For local synthetic generation and checks on a machine with Python 3.11+:

1. Clone the repository and enter its root.
2. Run `python -m pip install -e ".[dev]"` to install the simulator, PyArrow, tests, and lint dependencies.
3. Run `python -m plant.generate --scenario S1 --seed 42` to generate the 70-day synthetic Parquet dataset under `data/generated/`.
4. Run `python -m pytest` and `python -m ruff check .` to verify the current implementation.
5. Use `twin.estimator.estimate_states`, `twin.calibrate.calibrate_from_estimates`, `twin.simulate.simulate` / `simulate_ensemble`, and `twin.what_if.what_if` for Phase 2 analyses. The corresponding API and gaps are described in `docs/phase_2.md`.

`make data` invokes the generator where GNU Make is installed. `make train`, `make eval`, and `make demo` remain future-phase targets. There is no production hosting configuration, API, database, or real-facility integration yet. Final deployment steps must be updated after the API and dashboard phases.

## Known Phase 2 limits

The twin is simplified and uses synthetic telemetry. P2 is intentionally the naive idle-duration shutdown policy; break-even, dependency, warm-up, and minimum on/off constraints belong to the optimizer phase. The twin currently does not execute policies against the plant or report predicted-vs-realized policy outcomes.

## Next phase

Phase 3: implement forecasting, anomaly detection, waste/root-cause classification, and the evaluation harness skeleton. Keep validation splits by day and compare against the specified naive/threshold baselines.
