"""Constraint-checked rolling-horizon optimizer with deterministic solver-free fallback."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from contracts.models import (
    ControlAction,
    ControlCommand,
    EquipmentState,
    Recommendation,
    RecommendationConstraint,
    RecommendationImpact,
    RecommendationInterval,
    RecommendationPlan,
)
from twin.config import load_twin_config
from twin.model import MachineParameters, TwinSnapshot
from twin.simulate import _tariff_for_minute, simulate


@dataclass
class _Candidate:
    equipment: str
    action: ControlAction
    start: pd.Timestamp
    duration_min: int
    command: ControlCommand | None = None
    schedule: pd.DataFrame | None = None
    job_id: str | None = None
    constraints: list[RecommendationConstraint] | None = None
    action_parameters: dict[str, float | str] | None = None
    zone_machine_map: dict[str, str] | None = None


def break_even_minutes(machine: MachineParameters) -> float:
    """Return the minimum idle gap that makes standby worthwhile, including restart cost."""
    savings_kw = machine.p_idle_kw - machine.p_standby_kw
    restart_minutes = 0.0 if savings_kw <= 0 else 60.0 * machine.restart_kwh / savings_kw
    return max(float(machine.min_off_min), restart_minutes)


def check_constraints(
    candidate: _Candidate,
    snapshot: TwinSnapshot,
    schedule: pd.DataFrame,
    machines: dict[str, MachineParameters],
    machine_age_min: dict[str, int],
    horizon_min: int,
    peak_cap_kw: float | None,
    projected: Any | None = None,
) -> list[RecommendationConstraint]:
    """Apply production, state-age, dependency, comfort, and peak safety checks."""
    now = pd.Timestamp(snapshot.timestamp)
    end = now + pd.Timedelta(minutes=horizon_min)
    checks: list[RecommendationConstraint] = []

    def add(rule: str, passed: bool, detail: str) -> None:
        checks.append(RecommendationConstraint(rule=rule, passed=passed, detail=detail))

    machine = machines.get(candidate.equipment)
    if candidate.action == ControlAction.STANDBY and machine is not None:
        state = snapshot.machine_states.get(candidate.equipment, EquipmentState.OFF)
        age = machine_age_min.get(candidate.equipment, 0)
        add("machine_idle", state == EquipmentState.IDLE, f"Current state is {state.value}.")
        add(
            "minimum_on_time",
            age >= machine.min_on_min,
            f"State age {age} min; minimum on time {machine.min_on_min} min.",
        )
        future = (
            schedule[
                (pd.to_datetime(schedule.start_ts) >= now)
                & (pd.to_datetime(schedule.start_ts) <= end)
                & schedule.required_machines.map(
                    lambda value: candidate.equipment in str(value).split(",")
                )
            ]
            if not schedule.empty
            else schedule
        )
        starts = pd.to_datetime(future.start_ts) if not future.empty else pd.Series(dtype=object)
        next_start = starts.min() if len(starts) else end
        idle_gap = max(0.0, (next_start - now).total_seconds() / 60.0 - machine.warmup_min - 2)
        required_gap = break_even_minutes(machine)
        add(
            "break_even_idle_gap",
            idle_gap >= required_gap,
            f"Available idle gap {idle_gap:.1f} min; break-even threshold {required_gap:.1f} min.",
        )
        active_job = (
            schedule[
                (pd.to_datetime(schedule.start_ts) <= now)
                & (pd.to_datetime(schedule.end_ts) > now)
                & schedule.required_machines.map(
                    lambda value: candidate.equipment in str(value).split(",")
                )
            ]
            if not schedule.empty
            else schedule
        )
        critical = not active_job.empty and bool(active_job.get("critical", pd.Series(False)).any())
        if not schedule.empty and "critical" in schedule:
            upcoming_critical = schedule[
                schedule.critical.fillna(False).astype(bool)
                & (pd.to_datetime(schedule.start_ts) > now)
                & (
                    pd.to_datetime(schedule.start_ts)
                    <= now + pd.Timedelta(minutes=candidate.duration_min + machine.warmup_min + 2)
                )
                & schedule.required_machines.map(
                    lambda value: candidate.equipment in str(value).split(",")
                )
            ]
            critical = critical or not upcoming_critical.empty
        add("critical_job_protection", not critical, "Critical jobs cannot be interrupted.")
        if candidate.equipment == "C2":
            consumer_active = any(
                snapshot.machine_states.get(name) in {EquipmentState.RUNNING, EquipmentState.WARMUP}
                for name in ("CNC-02", "HP1")
            )
            consumer_needed = False
            if not schedule.empty:
                for row in schedule.itertuples():
                    required = str(row.required_machines).split(",")
                    if not set(required).intersection({"CNC-02", "HP1"}):
                        continue
                    job_start = pd.Timestamp(row.start_ts)
                    job_end = pd.Timestamp(row.end_ts)
                    if job_start <= now < job_end:
                        consumer_needed = True
                        break
                    lead = max(machines[mid].warmup_min for mid in required if mid in machines)
                    if (
                        now
                        <= job_start
                        <= now + pd.Timedelta(minutes=candidate.duration_min + lead)
                    ):
                        consumer_needed = True
                        break
            add(
                "compressor_dependency",
                not (consumer_active or consumer_needed),
                "C2 must remain available while a consumer is active or entering warm-up.",
            )
    elif candidate.action == ControlAction.PRE_WARM and machine is not None:
        state = snapshot.machine_states.get(candidate.equipment, EquipmentState.OFF)
        age = machine_age_min.get(candidate.equipment, 0)
        add(
            "machine_available_for_prewarm",
            state in {EquipmentState.OFF, EquipmentState.STANDBY},
            f"Current state is {state.value}.",
        )
        add(
            "minimum_off_time",
            age >= machine.min_off_min,
            f"State age {age} min; minimum off time {machine.min_off_min} min.",
        )
        needed = not schedule.empty and any(
            candidate.equipment in str(row.required_machines).split(",")
            and now <= pd.Timestamp(row.start_ts) <= end
            for row in schedule.itertuples()
        )
        add(
            "scheduled_production_need",
            needed,
            "Pre-warm must serve a scheduled job in the horizon.",
        )
    else:
        add("machine_idle", True, "Not a machine standby action.")
        add("minimum_on_time", True, "Not a machine standby action.")
        add("break_even_idle_gap", True, "Not a machine standby action.")
        add("critical_job_protection", True, "No critical production job is modified.")
        add("compressor_dependency", True, "No compressor shutdown is proposed.")

    if candidate.action == ControlAction.DEFER_JOB:
        job = schedule[schedule.job_id.astype(str) == str(candidate.job_id)]
        safe = not job.empty
        if safe:
            row = job.iloc[0]
            safe = bool(row.get("shiftable", False)) and not bool(row.get("critical", False))
            candidate_end = candidate.start + pd.Timedelta(minutes=candidate.duration_min)
            safe = safe and candidate.start >= pd.Timestamp(row.get("release_ts", row.start_ts))
            safe = safe and candidate_end <= pd.Timestamp(row.due_ts)
            shifted_schedule = candidate.schedule if candidate.schedule is not None else schedule
            shifted_row = shifted_schedule[
                shifted_schedule.job_id.astype(str) == str(candidate.job_id)
            ].iloc[0]
            shifted_start = pd.Timestamp(shifted_row.start_ts)
            shifted_end = pd.Timestamp(shifted_row.end_ts)
            required = set(str(shifted_row.required_machines).split(","))
            for other in shifted_schedule[
                shifted_schedule.job_id.astype(str) != str(candidate.job_id)
            ].itertuples():
                overlap = shifted_start < pd.Timestamp(other.end_ts) and shifted_end > pd.Timestamp(
                    other.start_ts
                )
                shared = required.intersection(str(other.required_machines).split(","))
                if overlap and shared:
                    safe = False
                    break
        add(
            "job_release_due_critical",
            safe,
            "Shiftable job stays within its due time and is not critical.",
        )
        add(
            "machine_exclusivity",
            safe,
            "Shifted job does not overlap another job on required machines.",
        )
    else:
        add("job_release_due_critical", True, "No job shift is proposed.")
        add("machine_exclusivity", True, "No job shift is proposed.")

    if candidate.action == ControlAction.LIGHTS_OFF:
        zone_id = candidate.equipment.removeprefix("LIGHTS:")
        active_in_zone = False
        zones_by_machine = {}
        if not schedule.empty:
            # The mapping is attached by candidate generation so a zone is only
            # switched off when its assigned stations have no scheduled demand.
            zones_by_machine = candidate.zone_machine_map or {}
            for row in schedule.itertuples():
                required = str(row.required_machines).split(",")
                if any(zones_by_machine.get(machine) == zone_id for machine in required):
                    if pd.Timestamp(row.start_ts) < end and pd.Timestamp(row.end_ts) > now:
                        active_in_zone = True
                        break
        add(
            "zone_occupancy",
            not active_in_zone and not snapshot.occupied,
            f"Zone {zone_id} has no scheduled demand and no current operator presence.",
        )

    if candidate.action == ControlAction.HVAC_SETBACK and projected is not None:
        comfort_ok = projected.kpis.comfort_violation_min == 0
        add(
            "occupied_comfort_band",
            comfort_ok,
            f"Projected comfort violations: {projected.kpis.comfort_violation_min} min.",
        )
    else:
        add("occupied_comfort_band", True, "No occupied comfort risk projected by this action.")

    if projected is not None and peak_cap_kw is not None:
        peak_ok = projected.kpis.peak_15min_kw <= peak_cap_kw
        add(
            "peak_cap",
            peak_ok,
            f"Projected peak {projected.kpis.peak_15min_kw:.2f} kW; cap {peak_cap_kw:.2f} kW.",
        )
    else:
        add("peak_cap", True, "No peak cap configured or projection supplied.")
    return checks


def _age_map(estimates: pd.DataFrame | None, snapshot: TwinSnapshot) -> dict[str, int]:
    ages: dict[str, int] = {
        machine: max(0, int(age)) for machine, age in snapshot.state_age_min.items()
    }
    if estimates is None or estimates.empty:
        return ages
    observed = estimates[pd.to_datetime(estimates.timestamp) <= pd.Timestamp(snapshot.timestamp)]
    for equipment, rows in observed.sort_values("timestamp").groupby("equipment_id"):
        current = snapshot.machine_states.get(equipment)
        if current is None:
            continue
        matching = rows.state.astype(str) == current.value
        age = 0
        for is_current in matching.iloc[::-1]:
            if not is_current:
                break
            age += 1
        ages[equipment] = age
    return ages


def _make_command(candidate: _Candidate, now: pd.Timestamp) -> ControlCommand | None:
    if candidate.action == ControlAction.DEFER_JOB:
        return None
    return ControlCommand(
        command_id=f"opt-{candidate.action.value.lower()}-{candidate.equipment}-{candidate.start:%Y%m%d%H%M}",
        issued_at=candidate.start.to_pydatetime(),
        equipment_id=candidate.equipment,
        action=candidate.action,
        duration_min=candidate.duration_min,
        rationale=f"Phase 5 optimizer recommendation for {candidate.action.value}.",
        setpoint_delta_c=(
            float(candidate.action_parameters["delta_c"])
            if candidate.action == ControlAction.HVAC_SETBACK
            and candidate.action_parameters
            and "delta_c" in candidate.action_parameters
            else None
        ),
    )


def _job_shift_candidate(
    schedule: pd.DataFrame,
    row: Any,
    now: pd.Timestamp,
    machines: dict[str, MachineParameters],
    slot: int,
    horizon_end: pd.Timestamp,
    tariff: dict[str, Any],
) -> _Candidate | None:
    if not bool(getattr(row, "shiftable", False)) or bool(getattr(row, "critical", False)):
        return None
    original_start, original_end = pd.Timestamp(row.start_ts), pd.Timestamp(row.end_ts)
    original_cost = sum(
        machines[mid].p_run_kw * _tariff_for_minute(ts.hour * 60 + ts.minute, tariff) / 60.0
        for mid in str(row.required_machines).split(",")
        if mid in machines
        for ts in pd.date_range(original_start, original_end - pd.Timedelta(minutes=1), freq="min")
    )
    best: tuple[float, pd.Timestamp, pd.DataFrame] | None = None
    due = pd.Timestamp(row.due_ts)
    for shift in range(
        slot, max(slot, int((due - original_start).total_seconds() // 60)) + 1, slot
    ):
        moved_start = original_start + pd.Timedelta(minutes=shift)
        moved_end = original_end + pd.Timedelta(minutes=shift)
        if moved_end > due or moved_end > horizon_end:
            continue
        conflict = False
        for other in schedule[schedule.job_id.astype(str) != str(row.job_id)].itertuples():
            if not set(str(row.required_machines).split(",")).intersection(
                str(other.required_machines).split(",")
            ):
                continue
            if moved_start < pd.Timestamp(other.end_ts) and moved_end > pd.Timestamp(
                other.start_ts
            ):
                conflict = True
                break
        if conflict:
            continue
        moved_cost = sum(
            machines[mid].p_run_kw * _tariff_for_minute(ts.hour * 60 + ts.minute, tariff) / 60.0
            for mid in str(row.required_machines).split(",")
            if mid in machines
            for ts in pd.date_range(moved_start, moved_end - pd.Timedelta(minutes=1), freq="min")
        )
        if moved_cost >= original_cost:
            continue
        modified = schedule.copy()
        mask = modified.job_id.astype(str) == str(row.job_id)
        modified.loc[mask, "start_ts"] = moved_start
        modified.loc[mask, "end_ts"] = moved_end
        saving = original_cost - moved_cost
        if best is None or saving > best[0]:
            best = (saving, moved_start, modified)
    if best is None:
        return None
    return _Candidate(
        equipment=f"JOB:{row.job_id}",
        action=ControlAction.DEFER_JOB,
        start=best[1],
        duration_min=int((original_end - original_start).total_seconds() // 60),
        schedule=best[2],
        job_id=str(row.job_id),
    )


def _candidates(
    snapshot: TwinSnapshot,
    schedule: pd.DataFrame,
    machines: dict[str, MachineParameters],
    estimates: pd.DataFrame | None,
    horizon_min: int,
    slot_min: int,
    facility: dict[str, Any],
    hvac_setback_c: float,
) -> list[_Candidate]:
    now = pd.Timestamp(snapshot.timestamp)
    end = now + pd.Timedelta(minutes=horizon_min)
    ages = _age_map(estimates, snapshot)
    tariff = yaml.safe_load(Path("config/tariff.yaml").read_text(encoding="utf-8"))
    candidates: list[_Candidate] = []
    for equipment, state in snapshot.machine_states.items():
        machine = machines.get(equipment)
        if machine is None or state != EquipmentState.IDLE:
            continue
        if ages.get(equipment, 0) < machine.min_on_min:
            continue
        future = (
            schedule[
                (pd.to_datetime(schedule.start_ts) > now)
                & (pd.to_datetime(schedule.start_ts) <= end)
                & schedule.required_machines.map(
                    lambda value, equipment=equipment: equipment in str(value).split(",")
                )
            ]
            if not schedule.empty
            else schedule
        )
        next_start = pd.to_datetime(future.start_ts).min() if not future.empty else end
        duration = int(max(1, min(horizon_min, (next_start - now).total_seconds() // 60)))
        candidate = _Candidate(equipment, ControlAction.STANDBY, now, duration)
        gap = next_start - now
        if (
            ages.get(equipment, 0) >= machine.min_on_min
            and gap.total_seconds() / 60 - machine.warmup_min - 2 >= break_even_minutes(machine)
        ):
            candidates.append(candidate)
    for equipment, state in snapshot.machine_states.items():
        machine = machines.get(equipment)
        if machine is None or state not in {EquipmentState.OFF, EquipmentState.STANDBY}:
            continue
        if ages.get(equipment, 0) < machine.min_off_min or schedule.empty:
            continue
        needed_jobs = schedule[
            (pd.to_datetime(schedule.start_ts) >= now)
            & (pd.to_datetime(schedule.start_ts) <= end)
            & schedule.required_machines.map(
                lambda value, equipment=equipment: equipment in str(value).split(",")
            )
        ]
        if needed_jobs.empty:
            continue
        next_start = pd.to_datetime(needed_jobs.start_ts).min()
        startup_lead = machine.min_off_min + machine.warmup_min + 2
        if (next_start - now).total_seconds() / 60 <= startup_lead:
            candidates.append(
                _Candidate(
                    equipment,
                    ControlAction.PRE_WARM,
                    now,
                    horizon_min,
                    action_parameters={"lead_min": float(startup_lead)},
                )
            )
    active_now = not schedule.empty and bool(
        ((pd.to_datetime(schedule.start_ts) <= now) & (pd.to_datetime(schedule.end_ts) > now)).any()
    )
    zones_by_machine = facility.get("lighting", {}).get("machine_zones", {})
    if not snapshot.occupied and 330 <= now.hour * 60 + now.minute < 1350:
        for zone_id in facility.get("lighting", {}).get("zones", []):
            candidates.append(
                _Candidate(
                    f"LIGHTS:{zone_id}",
                    ControlAction.LIGHTS_OFF,
                    now,
                    horizon_min,
                    action_parameters={"zone_id": str(zone_id)},
                    zone_machine_map=dict(zones_by_machine),
                )
            )
    if not snapshot.occupied and not active_now:
        candidates.append(
            _Candidate(
                "HVAC",
                ControlAction.HVAC_SETBACK,
                now,
                horizon_min,
                action_parameters={"delta_c": hvac_setback_c},
            )
        )
    for row in schedule.itertuples():
        if now <= pd.Timestamp(row.start_ts) < end:
            shifted = _job_shift_candidate(schedule, row, now, machines, slot_min, end, tariff)
            if shifted is not None:
                candidates.append(shifted)
    for candidate in candidates:
        candidate.command = _make_command(candidate, now)
    return candidates


def _objective(kpis: Any, co2_weight: float, late_job_penalty: float, peak_penalty: float) -> float:
    return float(
        kpis.cost_inr
        + co2_weight * kpis.co2_kg
        + late_job_penalty * kpis.late_jobs
        + peak_penalty * kpis.peak_15min_kw
    )


def _evaluate_candidate(
    candidate: _Candidate,
    snapshot: TwinSnapshot,
    schedule: pd.DataFrame,
    horizon_min: int,
    scenario: dict[str, Any],
    seeds: int,
    co2_weight: float,
    late_job_penalty: float,
    peak_penalty: float,
) -> tuple[RecommendationImpact, RecommendationInterval, float, float, Any]:
    base_values, candidate_values = [], []
    all_actions = []
    output_results = []
    candidate_schedule = candidate.schedule if candidate.schedule is not None else schedule
    for seed in range(seeds):
        uncertainty_rng = np.random.default_rng(np.random.SeedSequence([seed, 4521]))
        uncertain_states = dict(snapshot.machine_states)
        state_choices = [
            state
            for state in EquipmentState
            if state not in {EquipmentState.MAINTENANCE, EquipmentState.FAULT}
        ]
        for equipment, confidence in snapshot.confidence.items():
            if equipment in uncertain_states and uncertainty_rng.random() > confidence:
                uncertain_states[equipment] = state_choices[
                    int(uncertainty_rng.integers(len(state_choices)))
                ]
        perturbed_scenario = dict(scenario)
        perturbed_scenario["weather_mean_c"] = float(
            perturbed_scenario.get("weather_mean_c", 30.0)
        ) + float(uncertainty_rng.normal(0.0, perturbed_scenario.get("forecast_error_c", 0.7)))
        perturbed_snapshot = TwinSnapshot(
            timestamp=snapshot.timestamp,
            machine_states=uncertain_states,
            machine_power_kw=dict(snapshot.machine_power_kw),
            temperature_c=snapshot.temperature_c,
            occupied=snapshot.occupied,
            confidence=dict(snapshot.confidence),
            state_age_min=dict(snapshot.state_age_min),
        )
        baseline = simulate(perturbed_snapshot, schedule, [], horizon_min, perturbed_scenario, seed)
        controls = [candidate.command] if candidate.command is not None else []
        projected = simulate(
            perturbed_snapshot, candidate_schedule, controls, horizon_min, perturbed_scenario, seed
        )
        base_values.append(baseline.kpis)
        candidate_values.append(projected.kpis)
        output_results.append(projected)
        all_actions.append(
            _objective(baseline.kpis, co2_weight, late_job_penalty, peak_penalty)
            - _objective(projected.kpis, co2_weight, late_job_penalty, peak_penalty)
        )
    metric_names = {
        "energy_kwh": "energy_kwh",
        "cost_inr": "cost_inr",
        "co2_kg": "co2_kg",
        "peak_kw": "peak_15min_kw",
        "late_jobs": "late_jobs",
    }
    deltas = {
        key: np.array(
            [
                getattr(base, field) - getattr(action, field)
                for base, action in zip(base_values, candidate_values, strict=True)
            ],
            dtype=float,
        )
        for key, field in metric_names.items()
    }
    impact = RecommendationImpact(**{key: float(np.mean(values)) for key, values in deltas.items()})
    p05 = RecommendationImpact(
        **{key: float(np.quantile(values, 0.05)) for key, values in deltas.items()}
    )
    p95 = RecommendationImpact(
        **{key: float(np.quantile(values, 0.95)) for key, values in deltas.items()}
    )
    confidence = float(np.mean(np.asarray(all_actions) > 0))
    score = float(np.mean(all_actions))
    return impact, RecommendationInterval(p05=p05, p95=p95), score, confidence, output_results[0]


def optimize(
    snapshot: TwinSnapshot,
    schedule: pd.DataFrame,
    estimates: pd.DataFrame | None = None,
    scenario: dict[str, Any] | None = None,
    mode: str | None = None,
    cv_events: pd.DataFrame | None = None,
    config_path: str | Path = "config/optimizer.yaml",
    facility_path: str | Path = "config/facility.yaml",
) -> RecommendationPlan:
    """Build a deterministic 4-hour constrained recommendation plan.

    Recommendations are proposals only. The caller decides whether a human or an
    auto-policy applies them; this function never sends commands to the plant.
    """
    config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    selected_mode = mode or config.get("mode", "human")
    if selected_mode not in {"human", "auto"}:
        raise ValueError("mode must be 'human' or 'auto'")
    horizon = int(config.get("horizon_minutes", 240))
    seeds = int(config.get("ensemble_seeds", 30))
    slot = int(config.get("job_shift_slot_minutes", 15))
    machines, facility = load_twin_config(facility_path)
    peak_cap = config.get("peak_cap_kw")
    ages = _age_map(estimates, snapshot)
    co2_weight = float(config.get("co2_weight_inr_per_kg", 0.0))
    late_penalty = float(config.get("late_job_penalty_inr", 10000.0))
    peak_penalty = float(config.get("peak_penalty_inr_per_kw", 0.0))
    hvac_setback_c = float(config.get("hvac_setback_c", 2.0))
    candidates = _candidates(
        snapshot, schedule, machines, estimates, horizon, slot, facility, hvac_setback_c
    )
    accepted: list[Recommendation] = []
    rejected: list[dict[str, object]] = []
    selected_machines: set[str] = set()
    startup_bins: dict[int, int] = {}
    scored = []
    for candidate in candidates:
        impact, interval, score, confidence, projected = _evaluate_candidate(
            candidate,
            snapshot,
            schedule,
            horizon,
            scenario or {},
            seeds,
            co2_weight,
            late_penalty,
            peak_penalty,
        )
        checks = check_constraints(
            candidate, snapshot, schedule, machines, ages, horizon, peak_cap, projected
        )
        failed = [item for item in checks if not item.passed]
        if failed:
            rejected.append(
                {
                    "equipment": candidate.equipment,
                    "action": candidate.action.value,
                    "reason": "; ".join(f"{item.rule}: {item.detail}" for item in failed),
                }
            )
            continue
        if score <= 0:
            rejected.append(
                {
                    "equipment": candidate.equipment,
                    "action": candidate.action.value,
                    "reason": f"Expected objective improvement is {score:.3f}, not positive.",
                }
            )
            continue
        scored.append((score, candidate, impact, interval, confidence, checks, projected))
    scored.sort(
        key=lambda item: (
            -(item[0] / max(1, item[1].duration_min)),
            item[1].start,
            item[1].equipment,
        )
    )
    maximum_startups = int(config.get("max_concurrent_startups", 2))
    for score, candidate, impact, interval, confidence, checks, _projected in scored:
        identity = candidate.equipment
        startup_bin = int(
            (candidate.start - pd.Timestamp(snapshot.timestamp)).total_seconds() // 300
        )
        is_start = candidate.action == ControlAction.PRE_WARM
        if identity in selected_machines or (
            is_start and startup_bins.get(startup_bin, 0) >= maximum_startups
        ):
            rejected.append(
                {
                    "equipment": identity,
                    "action": candidate.action.value,
                    "reason": "Conflicts with another selected recommendation.",
                }
            )
            continue
        selected_machines.add(identity)
        if is_start:
            startup_bins[startup_bin] = startup_bins.get(startup_bin, 0) + 1
        checks.extend(
            [
                RecommendationConstraint(
                    rule="max_concurrent_startups",
                    passed=True,
                    detail=f"At most {maximum_startups} starts per 5-minute window.",
                ),
                RecommendationConstraint(
                    rule="objective_improvement",
                    passed=True,
                    detail=f"Expected weighted improvement {score:.2f} INR-equivalent.",
                ),
            ]
        )
        evidence: dict[str, object] = {
            "source": "twin_what_if",
            "seed_count": seeds,
            "scenario": dict(scenario or {}),
        }
        if candidate.job_id:
            evidence["job_id"] = candidate.job_id
        evidence["meter_window"] = [
            str(pd.Timestamp(snapshot.timestamp)),
            str(pd.Timestamp(snapshot.timestamp) + pd.Timedelta(minutes=15)),
        ]
        evidence["cv_event_ids"] = []
        if cv_events is not None and not cv_events.empty and "event_id" in cv_events:
            if "machine_id" in cv_events and not candidate.equipment.startswith("LIGHTS:"):
                matching_events = cv_events[
                    (cv_events.machine_id.astype(str) == candidate.equipment)
                    & (pd.to_datetime(cv_events.timestamp) <= pd.Timestamp(snapshot.timestamp))
                ].tail(15)
            else:
                matching_events = cv_events.iloc[:0]
            evidence["cv_event_ids"] = matching_events.event_id.astype(str).tolist()
        recommendation_id = (
            f"rec-{candidate.action.value.lower()}-"
            f"{candidate.equipment.replace(':', '-')}-{candidate.start:%Y%m%d%H%M}"
        )
        accepted.append(
            Recommendation(
                id=recommendation_id,
                ts=pd.Timestamp(snapshot.timestamp).to_pydatetime(),
                equipment=candidate.equipment,
                action=candidate.action,
                action_parameters=candidate.action_parameters or {},
                start=candidate.start.to_pydatetime(),
                duration_min=candidate.duration_min,
                projected=impact,
                interval=interval,
                constraints=checks,
                confidence=confidence,
                evidence=evidence,
                revert_if=(
                    [
                        "production demand detected",
                        "operator occupancy returns",
                        "comfort band breached",
                    ]
                    if candidate.action
                    in {ControlAction.STANDBY, ControlAction.LIGHTS_OFF, ControlAction.HVAC_SETBACK}
                    else ["job due-time risk detected"]
                ),
            )
        )
    return RecommendationPlan(mode=selected_mode, recommendations=accepted, rejected=rejected)
