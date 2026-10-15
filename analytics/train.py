"""Fit and persist Phase 3 normal-day analytics artifacts."""

import argparse
import json
from pathlib import Path

import joblib

from analytics.anomaly import fit_isolation_forest
from eval.harness import _estimates_for_split
from plant.simulator import load_facility
from twin.config import load_twin_config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="data/generated")
    parser.add_argument("--output", default="models/analytics.joblib")
    parser.add_argument("--config", default="config/facility.yaml")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    root = Path(args.input)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if not manifest.get("synthetic", False):
        raise ValueError("training requires generated data with a synthetic=true manifest")
    facility = load_facility(args.config)
    parameters, _ = load_twin_config(args.config)
    train_estimates = _estimates_for_split(root, "train", facility, parameters)
    model = fit_isolation_forest(train_estimates, seed=args.seed)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "model": model,
            "seed": args.seed,
            "training_split": "train",
            "training_days": manifest.get("split_days", {}).get("train"),
            "synthetic": True,
        },
        output,
    )
    print(f"Saved synthetic normal-day analytics model to {output}")


if __name__ == "__main__":
    main()
