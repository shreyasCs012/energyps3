# Phase 1 — plant simulator and data generation

## Built

- Added a ground-truth one-bay plant with five independently perturbed machines, one HVAC zone, three lighting zones, and an always-on base load.
- Added legal equipment state transitions with warmup, minimum-on, and minimum-off dwell tracking.
- Added seeded schedules, weather AR noise, machine-load variation, metering noise, HVAC thermal response, operator labels, and baseline idle behavior.
- Added separate anomaly-label generation and physical injection for forgotten-on equipment, compressor leaks, bearing degradation, lights left on, HVAC overcooling, and test-only sensor spike/dropout events.
- Added `python -m plant.generate`, which creates the seven requested Parquet tables and a manifest. Train/validation/test splits are by day; training has no injected anomalies and test includes unseen sensor anomalies in the configured 70-day run.
- Non-submetered machine power is null in telemetry. `state_true` and `operator_present_true` are evaluation-only labels and must be excluded from twin inputs.
- Oracle and simulated CV event modes are available. Video mode awaits the Phase 4 CV pipeline.

## How to run

```sh
python -m pip install -e ".[dev]"
python -m plant.generate --scenario S1 --seed 42
python -m pytest
```

The default generator writes the configured 70-day dataset to `data/generated/`. Use `python -m plant.generate --help` to select another scenario, seed, output directory, or day count.

## Verification

- `python -m pytest`: 10 passed (contract and plant tests).
- `python -m ruff check .`: passed.
- A 2-day simulated-CV generation completed and wrote all seven Parquet tables plus `manifest.json`; it contained 14,400 telemetry rows, 192 quarter-hour meter rows, and 14,400 CV rows.
- The normal-day calibrated sanity run was approximately 67.8% machines, 15.1% HVAC, 13.5% lighting, and 3.6% base load.
- Main-meter component totals reconcile exactly before meter noise; measured main meter stays within 1% in the sanity test.
- Same seed reproduces physical parameters, plant readings, and CV events.

## Known gaps

- The supplied three-zone lighting load is 4.2 kW and the baseline schedule keeps it on for 17 hours. That yields roughly 13–14% daily energy, above the spec's 5–8% target. The supplied power and schedule are retained; this mismatch is recorded in `ASSUMPTIONS.md`.
- Video-based CV, the twin, calibration, and policy-controlled plant execution are future phases.
- `state_true` and operator truth are stored alongside telemetry for evaluation convenience; consumers must explicitly drop these fields before model/twin ingestion.
- Synthetic schedules and physics are stylized and are not suitable for real plant control or savings claims.
