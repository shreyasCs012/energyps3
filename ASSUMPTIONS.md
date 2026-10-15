# Assumptions and implementation decisions

- The GitHub repository was empty at project start; Phases 0 and 1 establish the package structure and initial plant simulator from scratch.
- The supplied machine, tariff, weather, and emissions values are treated as configurable synthetic placeholders, not validated industrial measurements or cited live tariffs.
- Python 3.11 is the project baseline. Frontend and optional model dependencies will be introduced in the phases that use them.
- Generated datasets and local secrets are excluded from version control. Generated data records their seed, scenario, CV mode, split, and row counts in a manifest.
- The supplied lighting assumption (three 1.4 kW zones continuously on for 17 hours) yields about 13–14% of daily energy in the seeded normal-day sanity run. This is above the requested 5–8% range; the given per-zone power and schedule are preserved rather than silently changed. Phase 1 sanity bounds document this mismatch.
- Phase 1 jobs use seeded 2–4 hour synthetic durations, subject to shift capacity, to produce meaningful two-shift equipment utilization while keeping the configured 8–14 jobs/day range.
- Phase checkpoints are applied in the order requested by the master spec. The current checkpoint is Phase 1.

