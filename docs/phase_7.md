# Phase 7 — REST and WebSocket API

## What was built

- Added a FastAPI service for scenario listing, seeded synthetic runs, observable-input KPIs, recommendations, recommendation decisions, what-if simulation, a moving-average forecast, threshold anomaly alerts, CV events, Markdown reports, and copilot questions.
- Connected copilot tools to KPI calculation, the twin's `what_if`, forecast, and anomaly services. When configured provider credentials exist, the API enables the Phase 6 allowlisted LLM tool router; without credentials, regex intent routing remains available.
- Added `/ws/replay` for per-minute estimated twin state, meter readings, CV events, recommendations, policy selection, and scenario selection. Replay controls include speed 1×/10×/60×, pause/resume, and timestamp or index seek.
- Added typed API contracts with JSON Schema and TypeScript exports. Responses mark synthetic outputs explicitly.
- Recommendation apply, reject, and schedule endpoints record human workflow decisions in the current API process. They do not actuate the simulated or real plant.
- Updated `make demo` to run the API on loopback and documented the local workflow.

## How to run

```sh
python -m pip install -e ".[dev,api,cv]"
uvicorn api.app:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs`, then call `POST /run` with `{"scenario":"S1","seed":42,"days":1}` to create the active synthetic dataset. `make demo` runs the same loopback server. Set `ENERGYSENSE_DATA_DIR` and `ENERGYSENSE_REPORT_DIR` to change the local data and report locations. Optional LLM tool routing uses the Phase 6 environment settings.

The WebSocket accepts JSON controls such as `{"type":"speed","value":10}`, `{"type":"pause","value":true}`, `{"type":"seek","index":120}`, `{"type":"policy","value":"ai"}`, and `{"type":"scenario","value":"S2"}`. It sends a ready message followed by synthetic per-minute frames and a completion message.

## Verification

- `python -m pytest -q`: 53 passed. Warnings are from Starlette's TestClient/httpx deprecation notice and the existing benign Windows `joblib` physical-core detection fallback.
- `python -m ruff check .`: passed.
- `python -m ruff format --check .`: passed (72 files formatted).
- `python -m contracts.export_schema`: passed; new API schemas and TypeScript interfaces generated.
- `git diff --check`: passed.
- `npm run build` in `web/`: TypeScript and Vite production build passed.
- API integration tests exercise scenarios, run generation, KPI and forecast responses, anomaly and CV event outputs, what-if, copilot, report, recommendation decisions, invalid scenarios/equipment, and WebSocket pause/seek/replay.
- Feature commit: `01a7631 feat: add EnergySense REST and replay API`.

## Known gaps

- Forecasting currently exposes a transparent last-four-interval moving-average baseline. The trained model and walk-forward forecasting report are not served as live model forecasts.
- The anomaly endpoint exposes the threshold-alert baseline; model-based event scoring and evaluation labels are not returned as live detections.
- Apply/reject/schedule decisions live in memory and disappear when the API process restarts. The apply endpoint only approves a proposal; it sends no control commands.
- The API is a local prototype with no authentication, database, deployment manifest, or production hosting configuration. Keep the server on loopback until those are designed.
- Replay reads generated local data and emits CV events only; it does not store or stream source video frames.
