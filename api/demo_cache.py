"""Precompute a complete one-day synthetic S2 demo cache without starting the API."""

import json
from pathlib import Path
from typing import Any

from api.service import APIService
from contracts.models import RunRequest


def prepare_cache(root: str | Path = "demo_cache") -> dict[str, Any]:
    cache = Path(root)
    data = cache / "data"
    reports = cache / "reports"
    responses = cache / "responses"
    responses.mkdir(parents=True, exist_ok=True)
    service = APIService(data, reports)
    run = service.run(RunRequest(scenario="S2", seed=42, days=1))
    payloads = {
        "scenarios": service.scenarios(),
        "tariff": service.tariff(),
        "kpis": service.kpis().model_dump(mode="json"),
        "recommendations": service.recommendations("human"),
        "forecast": service.forecast(24),
        "anomalies": service.anomalies(),
        "cv_events": service.cv_events(limit=1000),
        "report": service.report(),
    }
    for name, value in payloads.items():
        (responses / f"{name}.json").write_text(
            json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8"
        )
    manifest = {
        "synthetic": True,
        "scenario": "S2",
        "seed": 42,
        "days": 1,
        "cv_mode": "simulated",
        "run": run["output_dir"],
        "cached_responses": sorted(payloads),
    }
    (cache / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    result = prepare_cache()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
