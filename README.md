# EnergySense Twin

EnergySense Twin is an offline-first prototype for exploring industrial energy waste with a synthetic plant simulator, a separately calibrated digital twin, constrained recommendations, and an explainable dashboard.

## Project status

Phases 0 through 9 are implemented. The ground-truth plant, calibrated twin, analytics, procedural video renderer, streaming CV pipeline, replay selection, constraint-checked recommendations, grounded explanations, offline copilot routing, JSON-driven reports, local REST/WebSocket API, React control-room dashboard, and paired held-out policy evaluation are available. Results remain synthetic and do not represent measured facility savings.

## Principles

- Plant ground truth and twin estimates are separate; the twin consumes telemetry and never reads plant internals.
- Runs are seeded and deterministic where applicable. All generated data is synthetic and all savings are simulation-based projections.
- The core demo is designed to work offline without a GPU or LLM key. CV and LLM use deterministic fallbacks; numeric claims in LLM explanations are checked against structured inputs.
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

`make data` generates the configured 70-day synthetic dataset into `data/generated/` using seed 42 and simulated CV events. Run `make train` for analytics model fitting and `make eval` for the final 20-seed × 4-scenario campaign; it writes policy and analytics results under `results/` and `reports/results.md`. `make eval-analytics` runs the standalone analytics harness on `data/generated/`. `make optimize` writes constraint-checked recommendations under `reports/optimizer/`, `make explain` renders grounded recommendation explanations, `make render` creates a procedural MP4 plus labels, and `make cv` ingests at least three source videos from `data/clips/manifest.csv`. Run `make demo-cache` once to precompute a synthetic S2 demo, then `make demo` to start the local API at `http://127.0.0.1:8000` with a 30× replay; `/docs` contains the API explorer. Without a demo cache, `make demo` generates the same one-day synthetic scenario when it starts. See [docs/phase_9.md](docs/phase_9.md) for evaluation outputs and limitations. Analytics are in `analytics/`, API in `api/`, CV in `cv/`, rendering in `renderer/`, replay selection in `replay/`, and recommendation planning in `policies/optimizer.py`.

The plant data keeps meter readings for non-submetered equipment unavailable. `state_true` and `operator_present_true` are retained as evaluation-only fields; downstream twin input code must explicitly exclude them.

## Configuration

Facility, tariff, scenarios, CV, and optimizer settings live in `config/`. Values in these files are explicit synthetic assumptions. Do not interpret them as measured facility data.

## Development

```sh
make lint
make format
make test
```

See [docs/phase_0.md](docs/phase_0.md), [docs/phase_1.md](docs/phase_1.md), [docs/phase_2.md](docs/phase_2.md), [docs/phase_3.md](docs/phase_3.md), [docs/phase_4.md](docs/phase_4.md), [docs/phase_5.md](docs/phase_5.md), [docs/phase_6.md](docs/phase_6.md), [docs/phase_7.md](docs/phase_7.md), [docs/phase_8.md](docs/phase_8.md), [docs/phase_9.md](docs/phase_9.md), [ASSUMPTIONS.md](ASSUMPTIONS.md), and [handoff.md](handoff.md) for project status and deployment steps.

