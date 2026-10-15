# EnergySense Twin

EnergySense Twin is an offline-first prototype for exploring industrial energy waste with a synthetic plant simulator, a separately calibrated digital twin, constrained recommendations, and an explainable dashboard.

## Project status

Phases 0 through 8 are implemented. The ground-truth plant, calibrated twin, analytics, procedural video renderer, streaming CV pipeline, replay selection, constraint-checked recommendations, grounded explanations, offline copilot routing, JSON-driven reports, local REST/WebSocket API, and React control-room dashboard are available. Full policy evaluation remains the final planned phase.

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

`make data` generates the configured 70-day synthetic dataset into `data/generated/` using seed 42 and simulated CV events. Run `make train` and `make eval` for analytics, `make optimize` to write constraint-checked recommendations under `reports/optimizer/`, `make explain` for grounded recommendation explanations, `make report` for Markdown from results JSON, `make render` for a procedural MP4 plus labels, and `make cv` after adding at least three source videos to `data/clips/manifest.csv`. CV normalizes each source clip and emits events without saving intermediate frames. Run `make demo` (or `uvicorn api.app:app --reload`) to start the local API at `http://127.0.0.1:8000`; call `POST /run` to generate a one-day synthetic dataset, then explore the API docs at `/docs`. Override generation options with `python -m plant.generate --help`; run `python -m policies.optimize --help` for optimizer inputs and mode options. Analytics are in `analytics/`, API in `api/`, CV in `cv/`, rendering in `renderer/`, replay selection in `replay/`, and recommendation planning in `policies/optimizer.py`.

The plant data keeps meter readings for non-submetered equipment unavailable. `state_true` and `operator_present_true` are retained as evaluation-only fields; downstream twin input code must explicitly exclude them.

## Configuration

Facility, tariff, scenarios, CV, and optimizer settings live in `config/`. Values in these files are explicit synthetic assumptions. Do not interpret them as measured facility data.

## Development

```sh
make lint
make format
make test
```

See [docs/phase_0.md](docs/phase_0.md), [docs/phase_1.md](docs/phase_1.md), [docs/phase_2.md](docs/phase_2.md), [docs/phase_3.md](docs/phase_3.md), [docs/phase_4.md](docs/phase_4.md), [docs/phase_5.md](docs/phase_5.md), [docs/phase_6.md](docs/phase_6.md), [docs/phase_7.md](docs/phase_7.md), [docs/phase_8.md](docs/phase_8.md), [ASSUMPTIONS.md](ASSUMPTIONS.md), and [handoff.md](handoff.md) for current status and next steps.

