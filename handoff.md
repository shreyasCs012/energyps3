# EnergySense Twin handoff

## Current state

Phase 0 scaffold is implemented. The source repository was initially empty. This is a synthetic-data prototype; no real facility data or validated savings claims are included.

## Work completed

- Added Python package metadata, lint/test settings, Makefile targets, CI workflow, and `.gitignore`.
- Added Pydantic contracts and JSON Schema/TypeScript export.
- Added baseline configuration for the one-bay facility, tariffs, scenarios, CV, and optimizer.
- Added a minimal React/Vite shell and project status documentation.
- Captured assumptions in `ASSUMPTIONS.md`; detailed phase record is in `docs/phase_0.md`.

## Verification and commits

- `python -m pytest`: 4 passed.
- `python -m ruff check .`: passed.
- `python -m contracts.export_schema`: passed and generated JSON Schema plus TypeScript contracts.
- All five YAML configs parsed successfully.
- `npm run build` in `web/`: passed.
- GNU Make is not installed in the Windows environment, so Makefile targets were verified using their underlying commands. Later phase targets are intentionally not available yet.
- Phase commit: `chore: scaffold EnergySense Twin project` on `main`; remote target is `origin/main`.

## Deployment steps

No production deployment is available at this checkpoint. For the Phase 0 scaffold on a machine with GNU Make, Python 3.11+, Node.js, and npm installed:

1. Clone the repository and enter its root.
2. Run `make setup` to install the Python package and development/API dependencies.
3. Run `make schema`, `make lint`, and `make test` to verify the contracts and Python scaffold.
4. In `web/`, run `npm install` and `npm run build` to build the app shell.

`make data`, `make train`, `make eval`, and `make demo` are not implemented in this phase and therefore are not deployment commands yet. There is no production hosting configuration, database, or real-facility integration at this checkpoint. Final deployment steps must be updated after the API and dashboard phases.

## Next phase

Phase 1: implement the separate ground-truth plant simulator, seeded data generators, configurable anomalies, and plant sanity/property checks. Do not let twin code import plant internals.

