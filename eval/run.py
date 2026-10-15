"""Run the Phase 3 analytics evaluation harness on generated Parquet data."""

import argparse
import json

from eval.harness import run_analytics_evaluation


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="data/generated")
    parser.add_argument("--output", default="reports/analytics")
    parser.add_argument("--config", default="config/facility.yaml")
    parser.add_argument("--anomaly-threshold-kw", type=float, default=35.0)
    args = parser.parse_args()
    report = run_analytics_evaluation(
        args.input, args.output, args.config, args.anomaly_threshold_kw
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
