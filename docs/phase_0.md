# Phase 0 — scaffold, contracts, and configuration

## Built

- Established the Python package layout and a minimal Vite/React TypeScript app shell.
- Added shared Pydantic v2 schemas for telemetry, commands, KPIs, and plant/twin comparisons.
- Added a command that exports JSON Schema and generated TypeScript interfaces from the contracts.
- Added facility, tariff, scenario, CV, and optimizer YAML configuration based on the supplied synthetic assumptions.
- Added Makefile targets, Python lint/test settings, a CI workflow, environment example, and generated-data ignore rules.
- Marked the project status and synthetic-data assumptions in the README.

## How to run

Requires Python 3.11+.

```sh
make setup
make schema
make lint
make test
```

The `data`, `train`, `eval`, and `demo` targets name future phase entry points and are not runnable until those modules exist.

## Verification

- `python -m pytest`: **4 passed** (contract validation).
- `python -m ruff check .`: passed after formatting and auto-fix.
- `python -m contracts.export_schema`: passed; generated four JSON Schema files and `web/src/contracts.ts`.
- YAML parse of all five `config/*.yaml` files: passed.
- `npm run build` from `web/`: passed (TypeScript check and Vite production build).
- `make` was not available in the Windows environment, so the underlying Python and npm commands were run directly.

## Known gaps

- The repository was empty, so the remaining phases are not present yet.
- The UI is only an app shell; it has no live simulation or dashboard functionality.
- The tariff and emissions values are illustrative placeholders and need a cited facility-specific source before operational use.
- A full clean-clone/offline run is not yet verifiable because later phase targets do not exist; the current React shell is buildable after installing npm dependencies.

