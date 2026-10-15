# EnergySense Twin

EnergySense Twin is an offline-first prototype for exploring industrial energy waste with a synthetic plant simulator, a separately calibrated digital twin, constrained recommendations, and an explainable dashboard.

## Project status

Phases 0 through 2 are implemented. The ground-truth plant, seeded schedule/weather/anomaly generation, Parquet data pipeline, separate state estimator, calibration, simplified twin simulation, what-if comparison, and P0–P2 policies are available. Analytics, real-video CV, optimization, API, dashboard, and full evaluation are planned phases and are not implemented yet.

## Principles

- Plant ground truth and twin estimates are separate; the twin consumes telemetry and never reads plant internals.
- Runs are seeded and deterministic where applicable. All generated data is synthetic and all savings are simulation-based projections.
- The core demo is designed to work offline without a GPU or LLM key. Optional CV/LLM upgrades will have deterministic fallbacks.
- Tariffs and grid emissions are configurable illustrative assumptions, not sourced utility rates. Cite and replace them for a real deployment.
- Evaluation must include baselines, held-out days, prediction-versus-realized results, and reported failures.

## Quick start

Requires Python 3.11 or newer.

```sh
make setup
make data
make test
make schema
```

`make data` generates the configured 70-day synthetic dataset into `data/generated/` using seed 42 and simulated CV events. Override options with `python -m plant.generate --help`. Phase 2 APIs are Python modules: `twin.estimator.estimate_states`, `twin.calibrate.calibrate_from_estimates`, `twin.simulate.simulate`, `twin.simulate.simulate_ensemble`, and `twin.what_if.what_if`. Policies are under `policies/`. `make train`, `make eval`, and `make demo` remain future-phase targets.

The plant data keeps meter readings for non-submetered equipment unavailable. `state_true` and `operator_present_true` are retained as evaluation-only fields; downstream twin input code must explicitly exclude them.

## Configuration

Facility, tariff, scenarios, CV, and optimizer settings live in `config/`. Values in these files are explicit synthetic assumptions. Do not interpret them as measured facility data.

## Development

```sh
make lint
make format
make test
```

See [docs/phase_0.md](docs/phase_0.md), [docs/phase_1.md](docs/phase_1.md), [docs/phase_2.md](docs/phase_2.md), [ASSUMPTIONS.md](ASSUMPTIONS.md), and [handoff.md](handoff.md) for current status and next steps.

