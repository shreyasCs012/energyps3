"""Build an optimizer plan from generated observable plant artifacts."""

import argparse
import json
from pathlib import Path

import pandas as pd
import yaml

from plant.simulator import load_facility
from policies.optimizer import optimize
from twin.config import load_twin_config
from twin.estimator import estimate_states, snapshot_from_estimates


def build_plan(
    input_dir: str | Path,
    timestamp: str,
    output_path: str | Path,
    mode: str = "human",
    config_path: str | Path = "config/optimizer.yaml",
    facility_path: str | Path = "config/facility.yaml",
    scenario_path: str | Path = "config/scenarios.yaml",
    scenario_name: str = "S1",
) -> dict[str, object]:
    """Estimate the current state using observable columns and write recommendations."""
    root = Path(input_dir)
    moment = pd.Timestamp(timestamp)
    day_start = moment.normalize()
    day_end = day_start + pd.Timedelta(days=1)
    telemetry = pd.read_parquet(root / "telemetry_1min.parquet")
    meter = pd.read_parquet(root / "main_meter_15min.parquet")
    hvac = pd.read_parquet(root / "hvac_temp.parquet")
    schedule = pd.read_parquet(root / "schedule.parquet")
    cv_events = pd.read_parquet(root / "cv_events.parquet")

    def within_day(frame: pd.DataFrame, column: str) -> pd.DataFrame:
        values = pd.to_datetime(frame[column])
        return frame[(values >= day_start) & (values < day_end)].copy()

    telemetry = within_day(telemetry, "timestamp")
    meter = within_day(meter, "interval_start")
    hvac = within_day(hvac, "timestamp")
    schedule = within_day(schedule, "start_ts")
    cv_events = within_day(cv_events, "timestamp")
    facility = load_facility(facility_path)
    machines, _ = load_twin_config(facility_path)
    estimates = estimate_states(
        telemetry,
        meter,
        cv_events,
        schedule,
        facility,
        hvac,
        machines,
    )
    temperature_column = next(
        (column for column in ("indoor_temp_c", "temperature_c", "temp_c") if column in hvac),
        None,
    )
    temperature = 24.0
    if temperature_column:
        observed_hvac = hvac[pd.to_datetime(hvac.timestamp) <= moment]
        if not observed_hvac.empty:
            temperature = float(observed_hvac.sort_values("timestamp").iloc[-1][temperature_column])
    occupied = False
    if not cv_events.empty and "operator_present" in cv_events:
        presence = cv_events[pd.to_datetime(cv_events.timestamp) <= moment].copy()
        if not presence.empty:
            station = "machine_id" if "machine_id" in presence else "camera_id"
            latest_presence = presence.sort_values("timestamp").groupby(station).tail(1)
            occupied = bool(latest_presence.operator_present.fillna(False).any())
    snapshot = snapshot_from_estimates(estimates, moment, temperature, occupied)
    scenario_config = yaml.safe_load(Path(scenario_path).read_text(encoding="utf-8"))
    scenario = dict(scenario_config["scenarios"][scenario_name])
    plan = optimize(
        snapshot,
        schedule,
        estimates=estimates,
        scenario=scenario,
        mode=mode,
        config_path=config_path,
        facility_path=facility_path,
        cv_events=cv_events,
    )
    payload = plan.model_dump(mode="json")
    payload["synthetic"] = True
    payload["snapshot_timestamp"] = moment.isoformat()
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="data/generated")
    parser.add_argument("--timestamp", default="2025-01-01T08:00:00+05:30")
    parser.add_argument("--output", default="reports/optimizer/recommendations.json")
    parser.add_argument("--mode", choices=("human", "auto"), default="human")
    parser.add_argument("--scenario", choices=("S1", "S2", "S3", "S4"), default="S1")
    parser.add_argument("--config", default="config/optimizer.yaml")
    parser.add_argument("--facility", default="config/facility.yaml")
    parser.add_argument("--scenarios", default="config/scenarios.yaml")
    args = parser.parse_args()
    payload = build_plan(
        args.input,
        args.timestamp,
        args.output,
        args.mode,
        args.config,
        args.facility,
        args.scenarios,
        args.scenario,
    )
    print(
        f"Wrote {len(payload['recommendations'])} recommendations "
        f"({len(payload['rejected'])} candidates rejected) to {args.output}"
    )


if __name__ == "__main__":
    main()
