"""Start a local API preloaded with a synthetic S2 replay at the UI's 30× speed."""

import argparse
import os
from pathlib import Path

import uvicorn

from api.app import create_app
from api.service import APIService
from contracts.models import RunRequest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    cache_root = Path(os.getenv("ENERGYSENSE_DEMO_CACHE", "demo_cache"))
    cache_data = cache_root / "data"
    cached_run = cache_data / "api_runs" / "S2-seed42"
    use_cache = (cached_run / "manifest.json").is_file()
    data_root = Path(
        os.getenv("ENERGYSENSE_DATA_DIR", str(cache_data if use_cache else "data/generated"))
    )
    report_root = Path(
        os.getenv(
            "ENERGYSENSE_REPORT_DIR", str(cache_root / "reports" if use_cache else "reports/api")
        )
    )
    service = APIService(data_root, report_root)
    if use_cache:
        service.response_cache_dir = cache_root / "responses"
        service.active_data_dir = cached_run
        print(f"Using precomputed synthetic S2 demo in {cached_run}")
    else:
        result = service.run(RunRequest(scenario="S2", seed=42, days=1))
        print(f"Generated synthetic S2 demo in {result['output_dir']}")
    print("Starting EnergySense Twin at 30× replay speed on /ws/replay")
    uvicorn.run(create_app(service), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
