# Phase 2 — Digital twin and baseline policies

## Built

- Added a separate twin model/config loader, evidence-based state estimator, snapshot builder, least-squares machine load calibration, and thermal parameter calibration.
- The estimator combines available submeters, CV events, schedule, HVAC, lighting, base load, and the main-meter residual for equipment without submeters. It selects only observable telemetry fields; plant truth labels are not inputs.
- Added minute-step twin simulation with energy, cost, carbon, demand, idle waste, restarts, throughput/late-job, temperature, comfort, and constraint KPIs; ensemble summaries; and baseline-vs-action what-if runs using common random numbers.
- Added P0 baseline, P1 threshold-alert, and P2 naive idle-shutdown policies. Policy configuration is in `config/policies.yaml`.
- Added synthetic held-out calibration tests including machine-power and main-meter MAPE, thermal recovery, hidden-truth isolation, simulation, ensemble, what-if, and policy checks.

## How to run

From the repository root with the development dependencies installed:

```sh
python -m pytest
python -m ruff check .
```

Import the Python interfaces directly: `estimate_states` from `twin.estimator`, `calibrate_from_estimates` from `twin.calibrate`, `simulate` and `simulate_ensemble` from `twin.simulate`, and `what_if` from `twin.what_if`. Policy evaluators are exposed in `policies.baseline`, `policies.threshold_alert`, and `policies.rule_idle_shutdown`.

## Verification

- `python -m pytest`: 15 passed.
- `python -m ruff check .`: passed.
- `python -m ruff format --check .`: passed.
- `git diff --check`: passed.

## Known gaps

- The simulator is a simplified twin and the policy runner does not yet execute commands against the plant; predicted-vs-realized policy evaluation belongs to later evaluation phases.
- P2 intentionally implements the naive idle-duration rule from the specification and does not enforce break-even, dependency, warm-up, or minimum on/off constraints. The optimizer phase must enforce those constraints.
- Ensemble uncertainty is a prototype over state confidence, load variation, and weather forecast error; CV and forecast models are not yet integrated.
- Main-meter MAPE is available when held-out meter/HVAC/facility inputs are passed to calibration. Thermal fitting is a separate optional least-squares call.
- All values and tests remain synthetic; no measured facility data or verified savings claims are included.
