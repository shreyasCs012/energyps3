"""Run paired held-out scenario, policy, forecast, anomaly, and CV evaluations."""

from __future__ import annotations

import argparse
import json
import math
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from contracts.models import ControlAction, ControlCommand, EquipmentState
from eval.harness import run_analytics_evaluation
from plant.generate import _choose_anomalies
from plant.simulator import PlantRun, load_facility, simulate_day
from policies.optimizer import optimize
from policies.rule_idle_shutdown import evaluate as idle_shutdown
from policies.threshold_alert import evaluate as threshold_alert
from twin.config import load_twin_config
from twin.estimator import STATE_POWER, estimate_states, snapshot_from_estimates

POLICY_NAMES = ("P0_baseline", "P1_threshold_alert", "P2_idle_shutdown", "P3_optimizer")
METRIC_NAMES = (
    "energy_kwh",
    "peak_15min_kw",
    "cost_inr",
    "co2_kg",
    "idle_waste_kwh",
    "restarts",
    "late_jobs",
    "comfort_violation_min",
    "constraint_violations",
    "command_failures",
)
STATES = [state.value for state in EquipmentState]


def _future_schedule_minutes(
    schedule: pd.DataFrame, equipment: str, times: pd.Series
) -> np.ndarray:
    starts = pd.to_datetime(
        schedule.loc[
            schedule.required_machines.astype(str).map(lambda value: equipment in value.split(",")),
            "start_ts",
        ]
    )
    current = pd.DatetimeIndex(pd.to_datetime(times))
    if starts.empty:
        return np.full(len(current), np.inf)
    offsets = pd.DatetimeIndex(starts.sort_values()).as_unit("ns").asi8
    at = current.as_unit("ns").asi8
    positions = offsets.searchsorted(at, side="left")
    result = np.full(len(current), np.inf)
    valid = positions < len(offsets)
    result[valid] = (offsets[positions[valid]] - at[valid]) / 60_000_000_000
    return result


def plant_kpis(run: PlantRun, facility: dict[str, Any]) -> dict[str, float | int]:
    """Calculate daily realized metrics only from ground-truth plant outputs."""
    components = run.components_minute
    power = components.main_meter_true_kw.to_numpy(dtype=float)
    times = pd.DatetimeIndex(pd.to_datetime(components.timestamp))
    interval_peak = pd.Series(power).groupby(np.arange(len(power)) // 15).mean()
    peak = float(interval_peak.max())
    tariff = yaml.safe_load(Path("config/tariff.yaml").read_text(encoding="utf-8"))
    rates = tariff["energy_inr_per_kwh"]
    hours = times.hour.to_numpy()
    peak_period = ((hours >= 9) & (hours < 12)) | ((hours >= 18) & (hours < 22))
    off_peak = (hours >= 22) | (hours < 6)
    rate = np.full(len(times), float(rates["normal"]))
    rate[peak_period] = float(rates["peak"])
    rate[off_peak] = float(rates["off_peak"])
    energy = float(power.sum() / 60.0)
    cost = float(np.dot(power / 60.0, rate)) + peak * float(
        tariff["demand_charge_inr_per_kw_month"]
    ) / float(tariff.get("demand_charge_proration_days", 30))

    state_frame = run.telemetry.pivot(
        index="timestamp", columns="equipment_id", values="state_true"
    )
    state_frame = state_frame.reindex(times)
    schedule = run.schedule
    idle_waste = 0.0
    restarts = 0
    machines = {item["id"]: item for item in facility["machines"]}
    for equipment, machine in machines.items():
        state = state_frame[equipment].astype(str)
        previous = state.shift(1)
        restarts += int(
            ((previous.isin({"OFF", "STANDBY"})) & state.isin({"WARMUP", "RUNNING", "IDLE"})).sum()
        )
        age = state.ne(state.shift()).cumsum()
        idle_duration = state.groupby(age).cumcount().to_numpy() + 1
        idle_duration[state.to_numpy() != "IDLE"] = 0
        idle_kw = components[f"machine:{equipment}_kw"].to_numpy(dtype=float)
        difference = float(machine["p_idle_kw"]) - float(machine["p_standby_kw"])
        break_even = (
            float(machine["restart_kwh"]) / difference * 60.0 if difference > 0 else math.inf
        )
        threshold = max(float(machine["min_off_min"]), break_even)
        next_start = _future_schedule_minutes(schedule, equipment, pd.Series(times))
        idle_mask = (
            (state.to_numpy() == "IDLE")
            & (idle_kw > 1.5 * float(machine["p_standby_kw"]))
            & (idle_duration > 10)
            & (next_start > threshold)
        )
        idle_waste += float(
            np.maximum(idle_kw[idle_mask] - float(machine["p_standby_kw"]), 0).sum() / 60
        )

    late_jobs = 0
    for job in schedule.itertuples():
        start = pd.Timestamp(job.start_ts)
        end = pd.Timestamp(job.end_ts)
        mask = (times >= start) & (times < end)
        if not mask.any():
            continue
        required = [item for item in str(job.required_machines).split(",") if item in state_frame]
        if required and not state_frame.loc[mask, required].eq("RUNNING").all(axis=None):
            late_jobs += 1
    occupied = run.hvac.occupied_true.fillna(False).to_numpy(dtype=bool)
    temperature = run.hvac.indoor_temp_c.to_numpy(dtype=float)
    comfort = int((occupied & ((temperature < 22.0) | (temperature > 27.0))).sum())

    consumer_active = state_frame[["CNC-02", "HP1"]].isin(["WARMUP", "RUNNING"]).any(axis=1)
    dependency_violations = int(
        (consumer_active & state_frame["C2"].isin(["OFF", "STANDBY"])).sum()
    )
    transition_violations = 0
    for equipment, machine in machines.items():
        values = state_frame[equipment].astype(str).to_numpy()
        age_in_state = 0
        powered_age = 0
        prior: str | None = None
        for value in values:
            if value != prior:
                if prior in {"OFF", "STANDBY"} and value in {"WARMUP", "IDLE", "RUNNING"}:
                    if age_in_state < int(machine["min_off_min"]):
                        transition_violations += 1
                if prior in {"WARMUP", "IDLE", "RUNNING"} and value in {"STANDBY", "OFF"}:
                    if powered_age < int(machine["min_on_min"]):
                        transition_violations += 1
                age_in_state = 0
                powered_age = 0 if value in {"OFF", "STANDBY"} else 1
            else:
                age_in_state += 1
                if value not in {"OFF", "STANDBY"}:
                    powered_age += 1
            prior = value
    return {
        "energy_kwh": energy,
        "peak_15min_kw": peak,
        "cost_inr": cost,
        "co2_kg": energy * float(tariff["grid_factor_kgco2_per_kwh"]),
        "idle_waste_kwh": idle_waste,
        "restarts": restarts,
        "late_jobs": late_jobs,
        "comfort_violation_min": comfort,
        "constraint_violations": dependency_violations + transition_violations,
    }


def _estimate_observations(
    run: PlantRun, facility: dict[str, Any], parameters: dict[str, Any]
) -> pd.DataFrame:
    return estimate_states(
        run.telemetry,
        run.meter_15min,
        run.cv_events,
        run.schedule,
        facility,
        run.hvac,
        parameters,
    )


def _commands_for_p2(estimates: pd.DataFrame) -> list[ControlCommand]:
    commands: list[ControlCommand] = []
    next_allowed: dict[str, pd.Timestamp] = {}
    for hour in (6, 8, 10, 12, 14, 16, 18, 20):
        moment = pd.Timestamp(estimates.timestamp.min()).normalize() + pd.Timedelta(hours=hour)
        history = estimates[pd.to_datetime(estimates.timestamp) <= moment]
        if history.empty:
            continue
        decision = idle_shutdown(history, idle_minutes=15, standby_duration_min=30)
        for command in decision.commands:
            equipment = command.equipment_id
            if moment < next_allowed.get(equipment, pd.Timestamp.min.tz_localize("UTC")):
                continue
            commands.append(command)
            next_allowed[equipment] = moment + pd.Timedelta(minutes=command.duration_min or 30)
    return commands


def _commands_for_p3(
    run: PlantRun,
    estimates: pd.DataFrame,
    facility: dict[str, Any],
    scenario: dict[str, Any],
    config_path: str | Path,
) -> tuple[list[ControlCommand], list[dict[str, Any]]]:
    commands: list[ControlCommand] = []
    predicted: list[dict[str, Any]] = []
    for hour in (8, 12, 16):
        moment = pd.Timestamp(estimates.timestamp.min()).normalize() + pd.Timedelta(hours=hour)
        if pd.Timestamp(estimates.timestamp.max()) < moment:
            continue
        history = estimates[pd.to_datetime(estimates.timestamp) <= moment]
        if history.empty:
            continue
        hvac = run.hvac[pd.to_datetime(run.hvac.timestamp) <= moment]
        temperature = float(hvac.iloc[-1].indoor_temp_c) if not hvac.empty else 24.0
        cv = run.cv_events[pd.to_datetime(run.cv_events.timestamp) <= moment]
        latest_cv = cv[pd.to_datetime(cv.timestamp) == pd.Timestamp(history.timestamp.max())]
        occupied = (
            bool(latest_cv.operator_present.fillna(False).any()) if not latest_cv.empty else False
        )
        snapshot = snapshot_from_estimates(history, moment, temperature, occupied)
        plan = optimize(
            snapshot,
            run.schedule,
            estimates=history,
            scenario=scenario,
            mode="auto",
            cv_events=cv,
            config_path=config_path,
        )
        for recommendation in plan.recommendations:
            predicted.append(
                {
                    "checkpoint": moment.isoformat(),
                    "recommendation_id": recommendation.id,
                    "action": recommendation.action.value,
                    "equipment": recommendation.equipment,
                    "projected": recommendation.projected.model_dump(mode="json"),
                }
            )
            if recommendation.action == ControlAction.DEFER_JOB:
                continue  # The plant command contract has no job-reschedule payload yet.
            parameters = recommendation.action_parameters
            commands.append(
                ControlCommand(
                    command_id=recommendation.id,
                    issued_at=recommendation.start,
                    equipment_id=recommendation.equipment,
                    action=recommendation.action,
                    duration_min=recommendation.duration_min,
                    rationale="Phase 9 paired synthetic policy evaluation.",
                    setpoint_delta_c=(
                        float(parameters["delta_c"])
                        if recommendation.action == ControlAction.HVAC_SETBACK
                        and "delta_c" in parameters
                        else None
                    ),
                )
            )
    return commands, predicted


def _cv_ablation(
    run: PlantRun,
    facility: dict[str, Any],
    parameters: dict[str, Any],
    scenario: dict[str, Any],
    config_path: str | Path,
) -> dict[str, Any]:
    """Compare planner inputs at controlled CV accuracies on one representative day."""
    truth = run.telemetry[["timestamp", "equipment_id", "state_true"]].rename(
        columns={"equipment_id": "machine_id", "state_true": "truth"}
    )
    events = run.cv_events.merge(truth, on=["timestamp", "machine_id"], how="inner")
    run_day = int(pd.Timestamp(run.telemetry.timestamp.min()).strftime("%Y%m%d"))
    rng = np.random.default_rng(np.random.SeedSequence([run_day, 911]))
    permutation = rng.permutation(len(events))
    variants: dict[str, pd.DataFrame] = {"no_cv": run.cv_events.iloc[0:0].copy()}
    for accuracy in (1.0, 0.92, 0.80):
        altered = events.copy()
        correct_count = int(round(len(altered) * accuracy))
        incorrect = set(permutation[correct_count:].tolist())
        states = [state.value for state in STATE_POWER]
        for index, row in enumerate(altered.itertuples()):
            if index in incorrect:
                alternatives = [state for state in states if state != row.truth]
                altered.at[index, "state"] = alternatives[
                    (index + int(accuracy * 100)) % len(alternatives)
                ]
            else:
                altered.at[index, "state"] = row.truth
        variants[f"cv_{int(accuracy * 100)}"] = altered.drop(columns="truth")

    results: dict[str, Any] = {}
    moment = pd.Timestamp(run.telemetry.timestamp.min()).normalize() + pd.Timedelta(hours=8)
    for name, cv_events in variants.items():
        estimates = estimate_states(
            run.telemetry, run.meter_15min, cv_events, run.schedule, facility, run.hvac, parameters
        )
        history = estimates[pd.to_datetime(estimates.timestamp) <= moment]
        if history.empty:
            results[name] = {
                "recommendation_count": 0,
                "accepted_count": 0,
                "projected_energy_kwh": 0.0,
            }
            continue
        hvac = run.hvac[pd.to_datetime(run.hvac.timestamp) <= moment]
        temperature = float(hvac.iloc[-1].indoor_temp_c) if not hvac.empty else 24.0
        latest_cv = cv_events[pd.to_datetime(cv_events.timestamp) == moment]
        occupied = (
            bool(latest_cv.operator_present.fillna(False).any()) if not latest_cv.empty else False
        )
        snapshot = snapshot_from_estimates(history, moment, temperature, occupied)
        plan = optimize(
            snapshot,
            run.schedule,
            estimates=history,
            scenario=scenario,
            mode="auto",
            cv_events=cv_events[pd.to_datetime(cv_events.timestamp) <= moment],
            config_path=config_path,
        )
        results[name] = {
            "recommendation_count": len(plan.recommendations),
            "constraint_pass_count": sum(
                all(constraint.passed for constraint in item.constraints)
                for item in plan.recommendations
            ),
            "rejected_candidate_count": len(plan.rejected),
            "projected_energy_kwh": float(
                sum(item.projected.energy_kwh for item in plan.recommendations)
            ),
            "actions": [item.action.value for item in plan.recommendations],
        }
    return results


def _summary(values: list[float]) -> dict[str, float | int]:
    array = np.asarray(values, dtype=float)
    mean = float(array.mean()) if len(array) else 0.0
    radius = float(1.96 * array.std(ddof=1) / math.sqrt(len(array))) if len(array) > 1 else 0.0
    return {
        "n": int(len(array)),
        "mean": mean,
        "ci95_low": mean - radius,
        "ci95_high": mean + radius,
        "std": float(array.std(ddof=1)) if len(array) > 1 else 0.0,
    }


def _metric_table(rows: list[dict[str, Any]], metric: str) -> dict[str, Any]:
    scenarios: dict[str, Any] = {}
    for scenario in sorted({row["scenario"] for row in rows}):
        scenarios[scenario] = {}
        selected_scenario = [row for row in rows if row["scenario"] == scenario]
        baseline = {
            row["seed"]: float(row[metric])
            for row in selected_scenario
            if row["policy"] == "P0_baseline"
        }
        for policy in POLICY_NAMES:
            group = [row for row in selected_scenario if row["policy"] == policy]
            values = [float(row[metric]) for row in group]
            paired = [float(row[metric]) - baseline[row["seed"]] for row in group]
            scenarios[scenario][policy] = {
                **_summary(values),
                "paired_delta_vs_P0": _summary(paired),
            }
    aggregate: dict[str, Any] = {}
    baseline_all = {
        (row["scenario"], row["seed"]): float(row[metric])
        for row in rows
        if row["policy"] == "P0_baseline"
    }
    for policy in POLICY_NAMES:
        group = [row for row in rows if row["policy"] == policy]
        values = [float(row[metric]) for row in group]
        deltas = [
            float(row[metric]) - baseline_all[(row["scenario"], row["seed"])] for row in group
        ]
        aggregate[policy] = {
            **_summary(values),
            "paired_delta_vs_P0": _summary(deltas),
        }
    return {"by_scenario": scenarios, "overall": aggregate}


def _save_campaign_dataset(
    path: Path, trials: list[tuple[PlantRun, str]], scenario: str, base_seed: int
) -> None:
    path.mkdir(parents=True, exist_ok=True)
    names = (
        "telemetry",
        "meter_15min",
        "hvac",
        "weather",
        "schedule",
        "anomaly_labels",
        "cv_events",
    )
    for name in names:
        frames = []
        file_names = {
            "telemetry": "telemetry_1min",
            "meter_15min": "main_meter_15min",
            "hvac": "hvac_temp",
            "weather": "weather",
            "schedule": "schedule",
            "anomaly_labels": "anomaly_labels",
            "cv_events": "cv_events",
        }
        for run, split in trials:
            frame = getattr(run, name).copy()
            frame["split"] = split
            frames.append(frame)
        pd.concat(frames, ignore_index=True).to_parquet(
            path / f"{file_names[name]}.parquet", index=False
        )
    split_counts = {
        key: sum(split == key for _, split in trials) for key in ("train", "validation", "test")
    }
    (path / "manifest.json").write_text(
        json.dumps(
            {
                "synthetic": True,
                "scenario": scenario,
                "seed": base_seed,
                "days": len(trials),
                "split_days": split_counts,
                "evaluation_campaign": True,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def run_policy_campaign(
    output_dir: str | Path = "results",
    seeds: int = 20,
    scenarios: tuple[str, ...] = ("S1", "S2", "S3", "S4"),
    campaign_seed: int = 42,
    optimizer_seeds: int = 3,
) -> dict[str, Any]:
    """Run a paired synthetic campaign and write machine-readable and Markdown reports."""
    if seeds < 3:
        raise ValueError("campaign needs at least 3 seeds to form day-level train/val/test splits")
    if optimizer_seeds < 1:
        raise ValueError("optimizer_seeds must be positive")
    output = Path(output_dir)
    data_root = output / "campaign_data"
    analytics_root = output / "analytics"
    analytics_root.mkdir(parents=True, exist_ok=True)
    facility = load_facility("config/facility.yaml")
    parameters, _ = load_twin_config("config/facility.yaml")
    scenario_config = yaml.safe_load(Path("config/scenarios.yaml").read_text(encoding="utf-8"))[
        "scenarios"
    ]
    optimizer_config = yaml.safe_load(Path("config/optimizer.yaml").read_text(encoding="utf-8"))
    optimizer_config["ensemble_seeds"] = optimizer_seeds
    with tempfile.TemporaryDirectory(prefix="energysense-eval-") as temporary:
        config_path = Path(temporary) / "optimizer.yaml"
        config_path.write_text(yaml.safe_dump(optimizer_config), encoding="utf-8")
        policy_rows: list[dict[str, Any]] = []
        analytics_reports: dict[str, Any] = {}
        cv_confusion = np.zeros((len(STATES), len(STATES)), dtype=np.int64)
        cv_names = {name: index for index, name in enumerate(STATES)}
        cv_correct = cv_total = 0
        cv_ablations: dict[str, Any] = {}
        started = time.perf_counter()

        for scenario_index, scenario_name in enumerate(scenarios):
            if scenario_name not in scenario_config:
                raise ValueError(f"unknown scenario {scenario_name!r}")
            observed_trials: list[tuple[PlantRun, str]] = []
            for index in range(seeds):
                split = (
                    "train"
                    if index < int(seeds * 0.7)
                    else ("validation" if index < int(seeds * 0.85) else "test")
                )
                trial_seed = int(
                    np.random.SeedSequence([campaign_seed, scenario_index, index]).generate_state(
                        1
                    )[0]
                )
                anomaly_rng = np.random.default_rng(np.random.SeedSequence([trial_seed, 8191]))
                anomalies = _choose_anomalies(split, index, anomaly_rng)
                run_date = date(2025, 1, 1) + timedelta(days=index)
                scenario = dict(scenario_config[scenario_name])
                baseline_run = simulate_day(
                    run_date,
                    trial_seed,
                    facility,
                    scenario,
                    anomalies,
                    "simulated",
                )
                observed_trials.append((baseline_run, split))
                baseline_metrics = plant_kpis(baseline_run, facility)
                alert_count = len(threshold_alert(baseline_run.meter_15min).alerts)
                estimates = _estimate_observations(baseline_run, facility, parameters)
                if index == 0:
                    cv_ablations[scenario_name] = _cv_ablation(
                        baseline_run, facility, parameters, scenario, config_path
                    )
                p2_commands = _commands_for_p2(estimates)
                p3_commands, p3_predictions = _commands_for_p3(
                    baseline_run, estimates, facility, scenario, config_path
                )
                policy_runs = {
                    "P0_baseline": (baseline_run, []),
                    "P1_threshold_alert": (baseline_run, []),
                    "P2_idle_shutdown": (
                        simulate_day(
                            run_date,
                            trial_seed,
                            facility,
                            scenario,
                            anomalies,
                            "simulated",
                            p2_commands,
                        ),
                        p2_commands,
                    ),
                    "P3_optimizer": (
                        simulate_day(
                            run_date,
                            trial_seed,
                            facility,
                            scenario,
                            anomalies,
                            "simulated",
                            p3_commands,
                        ),
                        p3_commands,
                    ),
                }
                projected_savings = {
                    "energy_kwh": sum(item["projected"]["energy_kwh"] for item in p3_predictions),
                    "cost_inr": sum(item["projected"]["cost_inr"] for item in p3_predictions),
                    "co2_kg": sum(item["projected"]["co2_kg"] for item in p3_predictions),
                    "peak_15min_kw": sum(item["projected"]["peak_kw"] for item in p3_predictions),
                    "late_jobs": sum(item["projected"]["late_jobs"] for item in p3_predictions),
                }
                for policy, (policy_run, commands) in policy_runs.items():
                    metrics = (
                        baseline_metrics
                        if policy == "P0_baseline"
                        else plant_kpis(policy_run, facility)
                    )
                    policy_rows.append(
                        {
                            "scenario": scenario_name,
                            "seed": trial_seed,
                            "day_index": index,
                            "split": split,
                            "policy": policy,
                            **metrics,
                            "command_count": len(commands),
                            "command_failures": sum(
                                bool(row["failed"]) for row in policy_run.command_outcomes
                            ),
                            "alert_count": alert_count if policy == "P1_threshold_alert" else 0,
                            "predicted_savings": projected_savings
                            if policy == "P3_optimizer"
                            else {},
                        }
                    )
                compared = baseline_run.cv_events.merge(
                    baseline_run.telemetry[["timestamp", "equipment_id", "state_true"]],
                    left_on=["timestamp", "machine_id"],
                    right_on=["timestamp", "equipment_id"],
                    how="inner",
                )
                for row in compared.itertuples():
                    actual_index = cv_names.get(str(row.state_true))
                    predicted_index = cv_names.get(str(row.state))
                    if actual_index is not None and predicted_index is not None:
                        cv_confusion[actual_index, predicted_index] += 1
                        cv_total += 1
                        cv_correct += int(actual_index == predicted_index)

            campaign_data = data_root / scenario_name
            _save_campaign_dataset(campaign_data, observed_trials, scenario_name, campaign_seed)
            analytics_reports[scenario_name] = run_analytics_evaluation(
                campaign_data,
                analytics_root / scenario_name,
            )

        metric_summaries = {metric: _metric_table(policy_rows, metric) for metric in METRIC_NAMES}
        p3_rows = [row for row in policy_rows if row["policy"] == "P3_optimizer"]
        prediction_validation: dict[str, Any] = {}
        for metric, prediction_name in (
            ("energy_kwh", "energy_kwh"),
            ("cost_inr", "cost_inr"),
            ("co2_kg", "co2_kg"),
            ("peak_15min_kw", "peak_15min_kw"),
            ("late_jobs", "late_jobs"),
        ):
            errors: list[float] = []
            predicted_values: list[float] = []
            realized_values: list[float] = []
            baseline_by_trial = {
                (row["scenario"], row["seed"]): row
                for row in policy_rows
                if row["policy"] == "P0_baseline"
            }
            for row in p3_rows:
                baseline = baseline_by_trial[(row["scenario"], row["seed"])]
                realized = float(baseline[metric]) - float(row[metric])
                predicted = float(row["predicted_savings"].get(prediction_name, 0.0))
                predicted_values.append(predicted)
                realized_values.append(realized)
                errors.append(predicted - realized)
            prediction_validation[metric] = {
                "predicted_savings": _summary(predicted_values),
                "realized_savings": _summary(realized_values),
                "prediction_error": _summary(errors),
                "interpretation": (
                    "Twin recommendations are evaluated individually over rolling 4-hour horizons; "
                    "their summed projections are compared with full-day plant realization "
                    "and may overlap."
                ),
            }

        report: dict[str, Any] = {
            "synthetic": True,
            "campaign": {
                "scenarios": list(scenarios),
                "seeds_per_scenario": seeds,
                "optimizer_ensemble_seeds": optimizer_seeds,
                "campaign_seed": campaign_seed,
                "policy_checkpoints": ["08:00", "12:00", "16:00"],
                "wall_time_seconds": round(time.perf_counter() - started, 2),
                "randomness": (
                    "paired scenario/seed plant runs with isolated exogenous noise streams"
                ),
            },
            "policies": list(POLICY_NAMES),
            "metrics": metric_summaries,
            "predicted_vs_realized": prediction_validation,
            "forecast_and_anomaly_evaluation": {
                scenario: {
                    "forecasting": metrics["forecasting"],
                    "anomaly_detection": metrics["anomaly_detection"],
                    "root_cause_rules": metrics["root_cause_rules"],
                    "root_cause_random_forest": metrics["root_cause_random_forest"],
                }
                for scenario, metrics in analytics_reports.items()
            },
            "cv_evaluation": {
                "states": STATES,
                "confusion_matrix": cv_confusion.tolist(),
                "accuracy": cv_correct / cv_total if cv_total else 0.0,
                "sample_count": cv_total,
                "planner_input_ablations": cv_ablations,
            },
            "policy_rows": policy_rows,
            "limitations": [
                "Synthetic results only; tariff and emissions remain illustrative assumptions.",
                "P1 is alert-only and therefore has the same plant KPIs as P0.",
                "The optimizer is replanned at three 4-hour checkpoints, not every 5 minutes.",
                "DEFER_JOB proposals are excluded from plant actuation because the command type "
                "has no reschedule payload.",
                "Policy P2 is intentionally naive and may harm schedule readiness; P3 is "
                "constraint-checked but not guaranteed to win.",
                "CV planner-input ablations are one representative day per scenario at the 08:00 "
                "checkpoint; they measure recommendation outputs, not plant-actuated outcomes.",
            ],
        }
    output.mkdir(parents=True, exist_ok=True)
    (output / "policy_evaluation.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (output / "policy_trials.csv").write_text(
        pd.DataFrame(policy_rows)
        .drop(columns=["predicted_savings"])
        .to_csv(index=False, lineterminator="\n"),
        encoding="utf-8",
        newline="\n",
    )
    markdown_path = (
        Path("reports/results.md")
        if output == Path("results")
        else output / "reports" / "results.md"
    )
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(render_markdown(report), encoding="utf-8", newline="\n")
    return report


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# EnergySense Twin — Phase 9 evaluation",
        "",
        "> **SYNTHETIC DATA — simulation-based projections.** "
        "This campaign is not measured facility performance.",
        "",
        "## Campaign design",
        "",
        f"- Scenarios: {', '.join(report['campaign']['scenarios'])}",
        f"- Seeds per scenario: {report['campaign']['seeds_per_scenario']}",
        f"- Optimizer ensemble seeds: {report['campaign']['optimizer_ensemble_seeds']}",
        f"- Policy checkpoints: {', '.join(report['campaign']['policy_checkpoints'])}",
        f"- Runtime: {report['campaign']['wall_time_seconds']} seconds",
        "- P0: plant baseline; P1: threshold alert only; P2: naive idle shutdown; "
        "P3: EnergySense optimizer.",
        "",
        "## Overall policy results",
        "",
        "Positive paired delta means the policy value exceeds baseline; for energy/cost/emissions, "
        "negative is an improvement.",
        "",
        "| Metric | Policy | Mean | 95% CI | Paired delta vs P0 (95% CI) |",
        "|---|---|---:|---:|---:|",
    ]
    for metric, results in report["metrics"].items():
        for policy, values in results["overall"].items():
            delta = values["paired_delta_vs_P0"]
            lines.append(
                f"| {metric} | {policy} | {values['mean']:.3f} | "
                f"[{values['ci95_low']:.3f}, {values['ci95_high']:.3f}] | "
                f"{delta['mean']:.3f} [{delta['ci95_low']:.3f}, {delta['ci95_high']:.3f}] |"
            )
    lines.extend(["", "## Optimizer predicted vs plant realized", ""])
    for metric, values in report["predicted_vs_realized"].items():
        pred = values["predicted_savings"]["mean"]
        realized = values["realized_savings"]["mean"]
        error = values["prediction_error"]["mean"]
        lines.append(
            f"- **{metric}:** projected {pred:.3f}; realized {realized:.3f}; "
            f"projection error {error:.3f}."
        )
    lines.extend(["", "## Forecast, anomaly, and root-cause evaluation", ""])
    for scenario, value in report["forecast_and_anomaly_evaluation"].items():
        lines.append(f"### {scenario}")
        lines.append("")
        for forecast in value["forecasting"]:
            lines.append(
                f"- Horizon {forecast.get('horizon_steps', '—')}: "
                f"{forecast.get('model', 'model')} MAE {forecast.get('mae', 0):.3f}, "
                f"RMSE {forecast.get('rmse', 0):.3f}."
            )
        anomaly = value["anomaly_detection"].get("threshold_alert_baseline", {})
        lines.append(
            f"- Threshold anomaly baseline: precision {anomaly.get('precision', 0):.3f}, "
            f"recall {anomaly.get('recall', 0):.3f}, F1 {anomaly.get('f1', 0):.3f}."
        )
        lines.append("")
    cv = report["cv_evaluation"]
    lines.extend(
        [
            "## CV state evaluation",
            "",
            f"- Simulated CV accuracy: {cv['accuracy']:.3f} across "
            f"{cv['sample_count']:,} minute-state observations.",
            f"- Confusion matrix states: {', '.join(cv['states'])}.",
            "- Full matrix is in `results/policy_evaluation.json`.",
            "",
            "## Limitations and failures",
            "",
        ]
    )
    # Insert decision-input ablations before the limitations section.
    limitation_start = lines.index("## Limitations and failures")
    ablation_lines = ["- Planner input ablations (one day per scenario at 08:00):"]
    for scenario, variants in cv.get("planner_input_ablations", {}).items():
        values = "; ".join(
            f"{name}: {result['recommendation_count']} recommendations, "
            f"{result['constraint_pass_count']} passing constraints"
            for name, result in variants.items()
        )
        ablation_lines.append(f"  - **{scenario}:** {values}.")
    ablation_lines.append("")
    lines[limitation_start:limitation_start] = ablation_lines
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.extend(
        [
            "- Confidence intervals use a normal approximation over paired seed-level outcomes; "
            "for 20 seeds they are descriptive rather than a formal guarantee.",
            "- Full artifacts: `results/policy_evaluation.json`, `results/policy_trials.csv`, "
            "and `results/analytics/<scenario>/`.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="results")
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--scenarios", nargs="+", default=["S1", "S2", "S3", "S4"])
    parser.add_argument("--campaign-seed", type=int, default=42)
    parser.add_argument("--optimizer-seeds", type=int, default=3)
    args = parser.parse_args()
    report = run_policy_campaign(
        args.output,
        args.seeds,
        tuple(args.scenarios),
        args.campaign_seed,
        args.optimizer_seeds,
    )
    print(
        json.dumps(
            {
                "results": str(Path(args.output) / "policy_evaluation.json"),
                "markdown": "reports/results.md",
                "trials": len(report["policy_rows"]),
                "runtime_seconds": report["campaign"]["wall_time_seconds"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
