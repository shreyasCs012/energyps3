# EnergySense Twin handoff

## Current state

Phases 0 and 1 are implemented. The source repository was initially empty. This is a synthetic-data prototype; no real facility data or validated savings claims are included.

## Work completed

- Added Python package metadata, lint/test settings, Makefile targets, CI workflow, and `.gitignore`.
- Added Pydantic contracts and JSON Schema/TypeScript export.
- Added baseline configuration for the one-bay facility, tariffs, scenarios, CV, and optimizer.
- Added a minimal React/Vite shell and project status documentation.
- Added the seeded ground-truth plant, state machine, daily schedule and weather generation, anomaly injection/labels, and Parquet dataset writer.
- Captured assumptions in `ASSUMPTIONS.md`; phase records are in `docs/phase_0.md` and `docs/phase_1.md`.

## Verification and commits

- `python -m pytest`: 4 passed.
- `python -m ruff check .`: passed.
- `python -m contracts.export_schema`: passed and generated JSON Schema plus TypeScript contracts.
- All five YAML configs parsed successfully.
- `npm run build` in `web/`: passed.
- Phase 1 `python -m pytest`: 10 passed.
- Phase 1 `python -m ruff check .`: passed.
- Phase 1 generated a two-day simulated-CV Parquet smoke dataset successfully; see `docs/phase_1.md` for artifacts and row counts.
- GNU Make is not installed in the Windows environment, so Makefile targets were verified using their underlying commands.
- Phase commits are pushed to `origin/main`: `chore: scaffold EnergySense Twin project` and `feat: add seeded plant simulator and data generation`.

## Deployment steps

No production deployment is available at this checkpoint. For local Phase 1 data generation on a machine with Python 3.11+:

1. Clone the repository and enter its root.
2. Run `python -m pip install -e ".[dev]"` to install the simulator, PyArrow, tests, and lint dependencies.
3. Run `python -m plant.generate --scenario S1 --seed 42` to generate the 70-day synthetic Parquet dataset under `data/generated/`.
4. Run `python -m pytest` and `python -m ruff check .` to verify the current implementation.

`make data` now invokes the generator when GNU Make is installed. `make train`, `make eval`, and `make demo` remain future-phase targets. There is no production hosting configuration, API, database, or real-facility integration yet. Final deployment steps must be updated after the API and dashboard phases.

## Next phase

Phase 2: add the separate twin estimator, calibration, simulation/what-if interfaces, and baseline/threshold/rule policies. Twin inputs must exclude plant internals and evaluation truth labels.

