# Phase 8 — React dashboard

## Delivered

- Replaced the placeholder with a responsive industrial control-room dashboard: Live floor, Twin simulation, Recommendations, Analytics, and Impact report.
- Connected scenario/run selection, KPI/report/forecast/anomaly/recommendation REST calls, recommendation decisions, copilot requests, and the controllable WebSocket replay.
- Exposed the configured illustrative tariff through a read-only API route so the dashboard's live run-rate cost uses the same rates as the backend KPI calculation.
- Added replay pause, 1×/10×/60× speed, start seek, live machine estimates, meter and twin load charts, camera event signals, tariff and cost estimates, and recommendation constraint/evidence summaries.
- Added a visible synthetic-data badge and scope/assumption copy throughout the dashboard. The impact report exports the API Markdown response.
- Added a Vite development proxy for the local API and WebSocket, so local UI/API development does not need permissive cross-origin API settings.

## Verification

- `npm run build` in `web/`: passed with TypeScript and Vite production compilation. Vite reports the Recharts bundle is over 500 kB minified; the current build is usable, and code splitting is a future optimization.
- `python -m pytest -q`: 53 passed. Warnings: Starlette's httpx TestClient deprecation and benign Windows `joblib` physical-core detection fallback.
- `python -m ruff check .`: passed.
- `python -m ruff format --check .`: passed (72 files already formatted).
- `git diff --check`: passed.
- Local API smoke: loaded scenarios, generated S2 / seed 42 / one synthetic day through `POST /run`, then successfully read KPIs, a four-point forecast, and report.
- A browser harness could not reach the temporary Vite dev-server port in this environment; frontend UI behavior was verified by the production build, and API routes by the local smoke plus API tests.

## Run locally

Start the API from the repository root:

```sh
python -m pip install -e ".[dev,api,cv]"
uvicorn api.app:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```sh
cd web
npm install
npm run dev
```

Open the Vite URL (normally `http://localhost:5173`), choose a scenario, and click **Run simulation**. The dashboard generates its own one-day synthetic run. The Vite proxy forwards API and WebSocket paths to `127.0.0.1:8000`. Set `VITE_API_URL` at build time only when serving the UI and API on separate origins; configure the API's CORS policy for that deployment.

## Known scope

- Analytics UI shows the API's moving-average forecast and threshold events. Offline train/evaluation artifacts are not exposed by the current API, so confusion matrices, forecast-vs-naive scores, and calibration curves are explicitly marked unavailable.
- Meter load and sum of equipment estimates are drawn as distinct series; they are not presented as equivalent or as a validated AI-policy counterfactual.
- The current CV API provides event signals, not camera video or thumbnails. Recommendation evidence is text-only where supplied.
- Export is Markdown. PDF generation, production hosting, authentication, multi-user persistence, and control actuation are outside this phase.
