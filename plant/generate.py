"""Generate reproducible synthetic plant data and split-safe labels."""

import argparse
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from plant.simulator import KNOWN_ANOMALIES, UNSEEN_ANOMALIES, PlantRun, load_facility, simulate_day


def _choose_anomalies(split: str, index: int, rng: np.random.Generator) -> list[str]:
    if split == "train":
        return []
    candidates = list(KNOWN_ANOMALIES)
    if split == "test":
        candidates.extend(UNSEEN_ANOMALIES)
    # Cycle through labels to make each known type appear in validation/test days.
    primary = candidates[index % len(candidates)]
    if rng.random() < 0.6:
        return [primary]
    secondary = str(rng.choice([name for name in candidates if name != primary]))
    return [primary, secondary]


def generate_dataset(
    facility_path: str | Path,
    scenario_path: str | Path,
    scenario_name: str,
    seed: int,
    output_dir: str | Path,
    days: int | None = None,
    cv_mode: str | None = None,
) -> dict[str, Any]:
    """Generate daily runs and write the Phase 1 Parquet artifacts."""
    facility = load_facility(facility_path)
    scenario_config = yaml.safe_load(Path(scenario_path).read_text(encoding="utf-8"))
    scenario = dict(scenario_config["scenarios"][scenario_name])
    day_count = int(days or scenario_config.get("days", 70))
    split_cfg = scenario_config.get("split", {"train": 56, "validation": 7, "test": 7})
    split_counts = [int(split_cfg["train"]), int(split_cfg["validation"]), int(split_cfg["test"])]
    if sum(split_counts) != day_count:
        if days is None:
            raise ValueError(
                "Configured train/validation/test day counts must sum to configured days"
            )
        # Small local/demo generations remain useful while preserving a day-level split.
        train_count = max(1, int(day_count * split_counts[0] / sum(split_counts)))
        val_count = max(0, int(day_count * split_counts[1] / sum(split_counts)))
        test_count = day_count - train_count - val_count
        split_counts = [train_count, val_count, test_count]
    mode = cv_mode or str(scenario_config.get("cv_mode", "simulated"))
    if mode not in {"oracle", "simulated"}:
        raise ValueError(
            "Video CV generation is available starting in Phase 4; use oracle or simulated for now"
        )

    frames: dict[str, list[pd.DataFrame]] = {
        "telemetry_1min": [],
        "main_meter_15min": [],
        "hvac_temp": [],
        "weather": [],
        "schedule": [],
        "anomaly_labels": [],
        "cv_events": [],
    }
    split_names = (
        ["train"] * split_counts[0] + ["validation"] * split_counts[1] + ["test"] * split_counts[2]
    )
    start_date = date(2025, 1, 1)
    label_rng = np.random.default_rng(np.random.SeedSequence([seed, 8_981]))
    for index, split_name in enumerate(split_names):
        run_day = start_date + timedelta(days=index)
        anomalies = _choose_anomalies(split_name, index - split_counts[0], label_rng)
        day_seed = int(np.random.SeedSequence([seed, index]).generate_state(1)[0])
        run: PlantRun = simulate_day(run_day, day_seed, facility, scenario, anomalies, mode)
        for table_name, frame in (
            ("telemetry_1min", run.telemetry),
            ("main_meter_15min", run.meter_15min),
            ("hvac_temp", run.hvac),
            ("weather", run.weather),
            ("schedule", run.schedule),
            ("anomaly_labels", run.anomaly_labels),
            ("cv_events", run.cv_events),
        ):
            value = frame.copy()
            value["split"] = split_name
            value["scenario"] = scenario_name
            frames[table_name].append(value)

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    row_counts: dict[str, int] = {}
    for table_name, pieces in frames.items():
        combined = pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame()
        combined.to_parquet(root / f"{table_name}.parquet", index=False)
        row_counts[table_name] = len(combined)
    manifest = {
        "synthetic": True,
        "seed": seed,
        "scenario": scenario_name,
        "cv_mode": mode,
        "days": day_count,
        "split_days": {
            "train": split_counts[0],
            "validation": split_counts[1],
            "test": split_counts[2],
        },
        "train_anomalies": 0,
        "test_unseen_anomalies": list(UNSEEN_ANOMALIES),
        "rows": row_counts,
        "note": (
            "state_true and operator_present_true are evaluation-only labels; "
            "exclude them from twin inputs."
        ),
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/facility.yaml")
    parser.add_argument("--scenarios", default="config/scenarios.yaml")
    parser.add_argument("--scenario", choices=("S1", "S2", "S3", "S4"), default="S1")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--days", type=int, default=None)
    parser.add_argument("--cv-mode", choices=("oracle", "simulated"), default=None)
    parser.add_argument("--output", default="data/generated")
    args = parser.parse_args()
    manifest = generate_dataset(
        args.config, args.scenarios, args.scenario, args.seed, args.output, args.days, args.cv_mode
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
