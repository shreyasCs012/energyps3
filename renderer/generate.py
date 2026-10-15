"""Render a reproducible synthetic plant video and frame-level labels."""

import argparse
from datetime import date

import pandas as pd

from plant.simulator import load_facility, simulate_day
from renderer.render import render_video


def render_scenario(
    output_video: str,
    output_labels: str,
    day: date = date(2025, 1, 1),
    seed: int = 42,
    minutes: int = 1440,
    facility_path: str = "config/facility.yaml",
) -> pd.DataFrame:
    """Run the hidden plant only to create labeled synthetic renderer inputs."""
    if not 1 <= minutes <= 1440:
        raise ValueError("minutes must be between 1 and 1440")
    facility = load_facility(facility_path)
    run = simulate_day(day, seed, facility, cv_mode="oracle")
    telemetry = run.telemetry.loc[
        :, ["timestamp", "equipment_id", "state_true", "operator_present_true"]
    ].copy()
    telemetry = telemetry.rename(columns={"state_true": "state"})
    lighting = run.components_minute.loc[:, ["timestamp", "lighting_kw"]].copy()
    lighting["lights_on"] = lighting.lighting_kw > 0
    timeline = telemetry.merge(lighting.loc[:, ["timestamp", "lights_on"]], on="timestamp")
    timeline = timeline[
        timeline.timestamp < timeline.timestamp.min() + pd.Timedelta(minutes=minutes)
    ]
    return render_video(timeline, output_video, output_labels)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", default="data/generated/renderer/synthetic.mp4")
    parser.add_argument("--labels", default="data/generated/renderer/labels.csv")
    parser.add_argument("--date", default="2025-01-01")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--minutes", type=int, default=1440)
    parser.add_argument("--config", default="config/facility.yaml")
    args = parser.parse_args()
    labels = render_scenario(
        args.video,
        args.labels,
        date.fromisoformat(args.date),
        args.seed,
        args.minutes,
        args.config,
    )
    print(f"Rendered {labels.timestamp.nunique()} labeled frames to {args.video}")


if __name__ == "__main__":
    main()
