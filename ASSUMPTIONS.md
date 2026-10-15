# Assumptions and implementation decisions

- The GitHub repository was empty at project start; Phases 0 and 1 establish the package structure and initial plant simulator from scratch.
- The supplied machine, tariff, weather, and emissions values are treated as configurable synthetic placeholders, not validated industrial measurements or cited live tariffs.
- Python 3.11 is the project baseline. Scikit-learn is used for the Phase 3 histogram gradient boosting, IsolationForest, and RandomForest models; no LightGBM dependency is required.
- Generated datasets and local secrets are excluded from version control. Generated data records their seed, scenario, CV mode, split, and row counts in a manifest.
- The supplied lighting assumption (three 1.4 kW zones continuously on for 17 hours) yields about 13–14% of daily energy in the seeded normal-day sanity run. This is above the requested 5–8% range; the given per-zone power and schedule are preserved rather than silently changed. Phase 1 sanity bounds document this mismatch.
- Phase 1 jobs use seeded 2–4 hour synthetic durations, subject to shift capacity, to produce meaningful two-shift equipment utilization while keeping the configured 8–14 jobs/day range.
- Phase 3 walk-forward scoring uses 15-minute origins and 1–6 hour horizons. Weather is omitted from forecast evaluation until a forecast input exists; schedule is treated as known future information.
- Phase 3's RandomForest root-cause classifier is fit on labeled validation-day events. Its five-class report is evaluated on separate test days, and any absent class or poor result remains visible in the report.
- Small smoke datasets may have zero validation days when proportional day allocation rounds to zero; the configured 70-day dataset retains the specified 56/7/7 split.
- Phase 4 transcodes source clips to MPEG-4 at a fixed resolution, cadence, bitrate, and deterministic grain before streaming features; decoded frames are never written to disk.
- CV source clips are split by clip ID before training-only augmentations. YOLO requires caller-supplied weights to prevent implicit downloads; OpenCV HOG is the offline people detector fallback.
- The procedural renderer uses plant truth only as a labeled synthetic video source. Those labels remain outside the twin input path.
- Replay selection returns looping clip offsets and crossfade metadata; actual compositing is left to a future replay UI/API.
- Phase 5 uses deterministic greedy selection by weighted projected benefit per action minute and a 15-minute feasible-slot search for flexible-job deferrals; it does not require OR-Tools. CO2 and lateness objective weights, horizon, ensemble size, peak cap, and HVAC setback are configurable in `config/optimizer.yaml`.
- Phase 5 recommendations are proposals only. The CLI exports JSON and does not actuate the plant; human approval/apply flow belongs to the API/dashboard phases.
- Phase 6 defaults to deterministic local explanations. Optional LLM calls use an OpenAI-compatible chat-completions endpoint configured by environment variables; output is only accepted when it passes the explanation contract and numeric grounding check. Provider-specific APIs may need a small adapter.
- Copilot tool implementations are injected callbacks so the core package stays offline and independent of API lifecycle; Phase 7 wires them to local twin and analytics services.
- The general Phase 6 Markdown report preserves supplied JSON values and does not infer missing metrics; Phase 9 adds a separate paired policy and analytics campaign report.
- Phase 7 API runs create seeded synthetic data under `data/generated/api_runs/`; their requested day count is explicit and defaults to one for interactive use.
- Phase 7 forecasts use a clearly labeled last-four-meter-interval moving average and anomaly alerts use the transparent threshold baseline until a live model serving interface is added.
- Recommendation apply/reject/schedule decisions are in-memory workflow records only. They issue no simulator or facility controls and are lost on process restart.
- The initial API is loopback-only local software without authentication or persistent API state. A production deployment requires later security, storage, and hosting decisions.
- The optimizer uses paired seeded twin projections with state-confidence and weather forecast perturbations. Projected KPI fields are baseline-minus-action deltas: positive values indicate savings/improvement and negative values indicate a projected increase.
- Phase 9 evaluates four synthetic scenarios across 20 paired seeds each; the optimizer uses a three-seed projection ensemble to keep campaign runtime practical, while standalone optimizer defaults remain unchanged.
- Phase checkpoints are applied in the order requested by the master spec. Phase 9 is the final checkpoint: 10 total phases numbered 0–9.

