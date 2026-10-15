"""Local service operations backed by generated synthetic tables and twin services."""

import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from analytics.anomaly import threshold_alerts
from contracts.models import ControlAction, ControlCommand, KPIResponse, RunRequest
from genai.copilot import Copilot, http_tool_router
from genai.report import generate_report
from plant.generate import generate_dataset
from plant.simulator import load_facility
from policies.optimize import build_plan
from twin.config import load_twin_config
from twin.estimator import estimate_states, snapshot_from_estimates
from twin.what_if import what_if as run_what_if


class APIService:
    """Coordinates generated runs, analytics responses, recommendation decisions and replay."""

    def __init__(
        self,
        data_dir: str | Path = "data/generated",
        report_dir: str | Path = "reports/api",
    ) -> None:
        self.data_dir = Path(data_dir)
        self.report_dir = Path(report_dir)
        self.active_data_dir = self.data_dir
        self.decisions: dict[str, dict[str, Any]] = {}
        self._plan_cache: dict[str, Any] | None = None
        self.facility_path = Path("config/facility.yaml")
        self.scenario_path = Path("config/scenarios.yaml")
        self.tariff_path = Path("config/tariff.yaml")

    def scenarios(self) -> list[dict[str, Any]]:
        config = yaml.safe_load(self.scenario_path.read_text(encoding="utf-8"))
        return [
            {"id": key, "name": value.get("name", key), "parameters": value}
            for key, value in config["scenarios"].items()
        ]

    def tariff(self) -> dict[str, Any]:
        config = yaml.safe_load(self.tariff_path.read_text(encoding="utf-8"))
        return {
            "currency": config.get("currency", "INR"),
            "energy_inr_per_kwh": config["energy_inr_per_kwh"],
            "peak_windows": config["peak_windows"],
            "synthetic": True,
        }

    def run(self, request: RunRequest) -> dict[str, Any]:
        known = {item["id"] for item in self.scenarios()}
        if request.scenario not in known:
            raise ValueError(f"unknown scenario {request.scenario!r}; choose from {sorted(known)}")
        destination = self.data_dir / "api_runs" / f"{request.scenario}-seed{request.seed}"
        manifest = generate_dataset(
            self.facility_path,
            self.scenario_path,
            request.scenario,
            request.seed,
            destination,
            request.days,
            request.cv_mode,
        )
        self.active_data_dir = destination
        self._plan_cache = None
        self.decisions.clear()
        return {
            "scenario": request.scenario,
            "seed": request.seed,
            "days": request.days,
            "synthetic": True,
            "output_dir": str(destination),
            "manifest": manifest,
        }

    def _table(self, table: str, root: Path | None = None) -> pd.DataFrame:
        directory = root or self.active_data_dir
        path = directory / f"{table}.parquet"
        if not path.exists():
            raise FileNotFoundError(
                f"missing {path}; generate a synthetic run with POST /run first"
            )
        return pd.read_parquet(path)

    def _manifest(self, root: Path | None = None) -> dict[str, Any]:
        path = (root or self.active_data_dir) / "manifest.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    @staticmethod
    def _day(frame: pd.DataFrame, column: str, selected: date) -> pd.DataFrame:
        if frame.empty or column not in frame:
            return frame.copy()
        values = pd.to_datetime(frame[column])
        return frame.loc[values.dt.date == selected].copy()

    def _daily_observations(self, selected: date | None = None) -> dict[str, pd.DataFrame | date]:
        meter = self._table("main_meter_15min")
        meter["interval_start"] = pd.to_datetime(meter.interval_start)
        selected_day = selected or meter.interval_start.max().date()
        tables = {
            "meter": self._day(meter, "interval_start", selected_day),
            "telemetry": self._day(self._table("telemetry_1min"), "timestamp", selected_day),
            "hvac": self._day(self._table("hvac_temp"), "timestamp", selected_day),
            "schedule": self._day(self._table("schedule"), "start_ts", selected_day),
            "cv": self._day(self._table("cv_events"), "timestamp", selected_day),
        }
        if tables["meter"].empty or tables["telemetry"].empty:
            raise ValueError(f"no generated observations are available for {selected_day}")
        tables["selected_day"] = selected_day
        return tables

    def _estimates(self, observations: dict[str, Any]) -> tuple[pd.DataFrame, dict, dict]:
        facility = load_facility(self.facility_path)
        machines, _ = load_twin_config(self.facility_path)
        estimates = estimate_states(
            observations["telemetry"],
            observations["meter"],
            observations["cv"],
            observations["schedule"],
            facility,
            observations["hvac"],
            machines,
        )
        return estimates, facility, machines

    def kpis(self, selected: date | None = None) -> KPIResponse:
        observations = self._daily_observations(selected)
        meter = observations["meter"].sort_values("interval_start")
        tariff = yaml.safe_load(self.tariff_path.read_text(encoding="utf-8"))
        hours = meter.interval_start.dt.hour
        peak = ((hours >= 9) & (hours < 12)) | ((hours >= 18) & (hours < 22))
        off_peak = (hours >= 22) | (hours < 6)
        rates = tariff["energy_inr_per_kwh"]
        rate_series = pd.Series(float(rates["normal"]), index=meter.index)
        rate_series.loc[peak] = float(rates["peak"])
        rate_series.loc[off_peak] = float(rates["off_peak"])
        interval_energy = meter.main_kw.astype(float) / 4.0
        energy = float(interval_energy.sum())
        cost = float((interval_energy * rate_series).sum())
        co2 = energy * float(tariff["grid_factor_kgco2_per_kwh"])
        estimates, _, machines = self._estimates(observations)
        schedule = observations["schedule"]
        waste_kwh = 0.0
        for equipment_id, machine in machines.items():
            rows = (
                estimates.loc[estimates.equipment_id == equipment_id]
                .sort_values("timestamp")
                .reset_index(drop=True)
            )
            timestamps = pd.DatetimeIndex(pd.to_datetime(rows.timestamp))
            states = rows.state.astype(str)
            run_ids = states.ne(states.shift()).cumsum()
            idle_duration = rows.groupby(run_ids).cumcount().to_numpy() + 1
            idle_duration[states.to_numpy() != "IDLE"] = 0
            jobs = (
                schedule.loc[
                    schedule.required_machines.astype(str).map(
                        lambda value, name=equipment_id: name in value.split(",")
                    )
                ]
                if not schedule.empty and "required_machines" in schedule
                else schedule.iloc[0:0]
            )
            starts = pd.DatetimeIndex(pd.to_datetime(jobs.start_ts).sort_values())
            active = pd.Series(False, index=rows.index)
            for job in jobs.itertuples():
                active |= (timestamps >= pd.Timestamp(job.start_ts)) & (
                    timestamps < pd.Timestamp(job.end_ts)
                )
            if len(starts):
                next_indices = starts.asi8.searchsorted(timestamps.asi8, side="left")
                has_next = next_indices < len(starts)
                next_delta = pd.Series(float("inf"), index=rows.index)
                next_delta.loc[has_next] = (
                    starts.asi8[next_indices[has_next]] - timestamps.asi8[has_next]
                ) / 60_000_000_000
            else:
                next_delta = pd.Series(float("inf"), index=rows.index)
            break_even = (
                machine.restart_kwh / (machine.p_idle_kw - machine.p_standby_kw) * 60.0
                if machine.p_idle_kw > machine.p_standby_kw
                else float("inf")
            )
            threshold = max(machine.min_off_min, break_even)
            waste = (
                states.eq("IDLE")
                & (rows.power_kw_estimate > 1.5 * machine.p_standby_kw)
                & ~active
                & (next_delta > threshold)
                & (idle_duration > 10)
            )
            waste_kwh += float(rows.loc[waste, "power_kw_estimate"].sum() / 60.0)
        idle_waste = waste_kwh
        ordered = estimates.sort_values(["equipment_id", "timestamp"])
        previous = ordered.groupby("equipment_id").state.shift(1)
        restart_states = {"WARMUP", "IDLE", "RUNNING"}
        restarts = int(
            ((previous.isin({"OFF", "STANDBY"})) & ordered.state.isin(restart_states)).sum()
        )
        late = 0
        if {"due_ts", "end_ts"}.issubset(schedule.columns):
            late = int((pd.to_datetime(schedule.end_ts) > pd.to_datetime(schedule.due_ts)).sum())
        comfort_minutes = 0
        hvac = observations["hvac"]
        cv = observations["cv"]
        if {"timestamp", "indoor_temp_c"}.issubset(hvac.columns) and {
            "timestamp",
            "operator_present",
        }.issubset(cv.columns):
            occupancy = cv.groupby(pd.to_datetime(cv.timestamp)).operator_present.any()
            temperatures = hvac.set_index(pd.to_datetime(hvac.timestamp)).indoor_temp_c
            paired = temperatures.to_frame("temp").join(occupancy.rename("occupied"), how="inner")
            comfort_minutes = int(
                (paired.occupied & ((paired.temp < 22.0) | (paired.temp > 27.0))).sum()
            )
        return KPIResponse(
            energy_kwh=energy,
            peak_15min_kw=float(meter.main_kw.max()),
            cost_inr=cost,
            co2_kg=co2,
            idle_waste_kwh=idle_waste,
            restarts=restarts,
            late_jobs=late,
            comfort_violation_min=comfort_minutes,
        )

    def _snapshot(
        self, timestamp: datetime | None = None
    ) -> tuple[Any, pd.DataFrame, dict[str, Any]]:
        observations = self._daily_observations(timestamp.date() if timestamp else None)
        estimates, _, _ = self._estimates(observations)
        moment = pd.Timestamp(timestamp) if timestamp else pd.Timestamp(estimates.timestamp.max())
        hvac = observations["hvac"]
        temp_col = next(
            (column for column in ("indoor_temp_c", "temperature_c", "temp_c") if column in hvac),
            None,
        )
        temperature = 24.0
        if temp_col:
            prior = hvac[pd.to_datetime(hvac.timestamp) <= moment].sort_values("timestamp")
            if not prior.empty:
                temperature = float(prior.iloc[-1][temp_col])
        snapshot = snapshot_from_estimates(estimates, moment, temperature)
        manifest = self._manifest()
        return snapshot, observations["schedule"], manifest

    def what_if(self, request: Any) -> dict[str, Any]:
        snapshot, schedule, manifest = self._snapshot(request.action.issued_at)
        machines, facility = load_twin_config(self.facility_path)
        equipment = request.action.equipment_id
        valid_equipment = set(machines) | {"HVAC", "LIGHTS"}
        valid_equipment |= {
            f"LIGHTS:{zone}" for zone in facility.get("lighting", {}).get("zones", [])
        }
        if equipment not in valid_equipment:
            raise ValueError(f"unknown equipment or zone {equipment!r}")
        if request.action.action == ControlAction.DEFER_JOB:
            raise ValueError("DEFER_JOB is not yet supported by twin.what_if")
        if (
            request.action.action in {ControlAction.STANDBY, ControlAction.PRE_WARM}
            and equipment not in machines
        ):
            raise ValueError(f"{request.action.action} requires a machine equipment_id")
        if request.action.action == ControlAction.HVAC_SETBACK and equipment != "HVAC":
            raise ValueError("HVAC_SETBACK requires equipment_id='HVAC'")
        if (
            request.action.action == ControlAction.HVAC_SETBACK
            and not request.action.setpoint_delta_c
        ):
            raise ValueError("HVAC_SETBACK requires a positive setpoint_delta_c")
        if request.action.action == ControlAction.LIGHTS_OFF and not (
            equipment == "LIGHTS" or equipment.startswith("LIGHTS:")
        ):
            raise ValueError("LIGHTS_OFF requires equipment_id='LIGHTS' or 'LIGHTS:<zone>'")
        scenario_name = request.scenario or manifest.get("scenario", "S1")
        scenarios = yaml.safe_load(self.scenario_path.read_text(encoding="utf-8"))["scenarios"]
        if scenario_name not in scenarios:
            raise ValueError(f"unknown scenario {scenario_name!r}")
        projected = run_what_if(
            snapshot,
            schedule,
            request.action,
            request.horizon_min,
            scenarios[scenario_name],
            request.seed,
        )
        return {
            "baseline": projected.baseline.kpis,
            "projected": projected.action.kpis,
            "delta": projected.delta,
            "seed": projected.seed,
            "synthetic": True,
        }

    def forecast(self, horizon_steps: int = 4) -> dict[str, Any]:
        if not 1 <= horizon_steps <= 24:
            raise ValueError("horizon_steps must be between 1 and 24 (up to six hours)")
        meter = self._table("main_meter_15min").sort_values("interval_start")
        if len(meter) < 4:
            raise ValueError("at least four meter intervals are needed for a forecast")
        baseline = float(meter.main_kw.tail(4).mean())
        start = pd.Timestamp(meter.interval_start.iloc[-1]) + pd.Timedelta(minutes=15)
        points = [
            {
                "timestamp": (start + pd.Timedelta(minutes=15 * index)).to_pydatetime(),
                "predicted_kw": max(0.0, baseline),
            }
            for index in range(horizon_steps)
        ]
        return {"method": "last-four-interval moving average", "points": points, "synthetic": True}

    def anomalies(self, threshold_kw: float = 35.0, selected: date | None = None) -> dict[str, Any]:
        if threshold_kw <= 0:
            raise ValueError("threshold_kw must be positive")
        observations = self._daily_observations(selected)
        alerts = threshold_alerts(observations["meter"], threshold_kw)
        events = alerts.loc[alerts.is_anomaly]
        return {
            "events": [
                {
                    "timestamp": row.timestamp.to_pydatetime(),
                    "main_kw": float(row.main_kw),
                    "threshold_kw": float(threshold_kw),
                    "score": float(row.anomaly_score),
                    "detector": "threshold_alert",
                }
                for row in events.itertuples()
            ],
            "synthetic": True,
        }

    def cv_events(self, selected: date | None = None, limit: int = 1000) -> dict[str, Any]:
        frame = self._table("cv_events")
        if selected:
            frame = self._day(frame, "timestamp", selected)
        allowed = [
            "timestamp",
            "camera_id",
            "machine_id",
            "zone_id",
            "state",
            "operator_present",
            "lights_on",
            "confidence",
            "clip_id",
        ]
        frame = frame.loc[:, [column for column in allowed if column in frame]].head(limit)
        return {
            "events": json.loads(frame.to_json(orient="records", date_format="iso")),
            "synthetic": True,
        }

    def recommendations(self, mode: str = "human") -> dict[str, Any]:
        if self._plan_cache is not None and self._plan_cache.get("mode") == mode:
            plan = self._plan_cache
        else:
            meter = self._table("main_meter_15min").sort_values("interval_start")
            moment = pd.Timestamp(meter.interval_start.iloc[0])
            manifest = self._manifest()
            scenario = manifest.get("scenario", "S1")
            target = self.report_dir / "recommendations.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            self._plan_cache = build_plan(
                self.active_data_dir,
                moment.isoformat(),
                target,
                mode=mode,
                scenario_name=scenario,
            )
            plan = self._plan_cache
        return {
            **plan,
            "synthetic": True,
            "decisions": list(self.decisions.values()),
        }

    def decide(self, recommendation_id: str, status: str, scheduled_for: datetime | None = None):
        plan = self.recommendations()
        ids = {item["id"] for item in plan["recommendations"]}
        if recommendation_id not in ids:
            raise KeyError(f"recommendation {recommendation_id!r} is not in the current plan")
        self.decisions[recommendation_id] = {
            "recommendation_id": recommendation_id,
            "status": status,
            "scheduled_for": scheduled_for,
        }
        messages = {
            "approved": (
                "Recommendation approved for the human-controlled workflow; "
                "no plant command was sent."
            ),
            "rejected": "Recommendation rejected; no plant command was sent.",
            "scheduled": "Recommendation scheduled in this API process; no plant command was sent.",
        }
        return {**self.decisions[recommendation_id], "message": messages[status]}

    def report(self) -> dict[str, Any]:
        kpis = self.kpis().model_dump(mode="json")
        results = {"synthetic": True, "scenario": self._manifest().get("scenario"), "kpis": kpis}
        return {"markdown": generate_report(results), "synthetic": True}

    def copilot(self) -> Copilot:
        def what_if_tool(args: dict[str, Any]) -> dict[str, Any]:
            query = str(args.get("query", ""))
            machine = args.get("equipment") or "CNC-01"
            action = (
                ControlAction.PRE_WARM
                if re.search(r"\b(pre.?warm|warm.?up)\b", query, re.I)
                else ControlAction.STANDBY
            )
            timestamp = pd.Timestamp(self._table("telemetry_1min").timestamp.max()).to_pydatetime()
            command = ControlCommand(
                command_id="copilot-what-if",
                issued_at=timestamp,
                equipment_id=str(machine),
                action=action,
                duration_min=60,
                rationale="Copilot simulation request; proposal only.",
            )
            from contracts.models import WhatIfRequest

            return self.what_if(WhatIfRequest(action=command))

        tools = {
            "what_if": what_if_tool,
            "get_kpis": lambda _args: self.kpis().model_dump(mode="json"),
            "list_anomalies": lambda _args: self.anomalies(),
            "forecast": lambda _args: self.forecast(),
        }
        return Copilot(
            tools,
            router=http_tool_router
            if os.getenv("LLM_PROVIDER") and os.getenv("LLM_API_KEY")
            else None,
        )

    def replay_frame(self, minute: datetime) -> dict[str, Any]:
        selected = minute.date()
        observations = self._daily_observations(selected)
        estimates, _, _ = self._estimates(observations)
        moment = pd.Timestamp(minute)
        minute_estimates = estimates[pd.to_datetime(estimates.timestamp) == moment]
        meter = observations["meter"]
        prior = meter[pd.to_datetime(meter.interval_start) <= moment]
        meter_kw = float(prior.iloc[-1].main_kw) if not prior.empty else None
        cv = observations["cv"]
        cv = cv[pd.to_datetime(cv.timestamp) == moment]
        plan: dict[str, Any] = {"recommendations": []}
        if self.decisions:
            # Keep the stream compact; the complete plan remains available over REST.
            plan = {"decisions": list(self.decisions.values())}
        return {
            "timestamp": moment.to_pydatetime(),
            "twin_state": json.loads(minute_estimates.to_json(orient="records", date_format="iso")),
            "meter_kw": meter_kw,
            "cv_events": json.loads(cv.to_json(orient="records", date_format="iso")),
            "recommendations": plan.get("recommendations", []),
        }

    def replay_events(self) -> list[dict[str, Any]]:
        telemetry = self._table("telemetry_1min")
        if telemetry.empty:
            raise ValueError("generated telemetry is empty")
        selected_day = pd.to_datetime(telemetry.timestamp).max().date()
        observations = self._daily_observations(selected_day)
        estimates, _, _ = self._estimates(observations)
        meter = (
            observations["meter"].sort_values("interval_start").set_index("interval_start").main_kw
        )
        cv = observations["cv"]
        if not cv.empty:
            cv = cv.drop(columns=[name for name in cv if name.endswith("_true")], errors="ignore")
            cv_groups = {
                pd.Timestamp(ts): json.loads(group.to_json(orient="records", date_format="iso"))
                for ts, group in cv.groupby(pd.to_datetime(cv.timestamp))
            }
        else:
            cv_groups = {}
        estimate_groups = {
            pd.Timestamp(ts): json.loads(group.to_json(orient="records", date_format="iso"))
            for ts, group in estimates.groupby(pd.to_datetime(estimates.timestamp))
        }
        moments = pd.DatetimeIndex(
            pd.to_datetime(telemetry.timestamp).drop_duplicates().sort_values()
        )
        meter_series = (
            meter.reindex(meter.index.union(moments)).sort_index().ffill().reindex(moments)
        )
        return [
            {
                "timestamp": moment.to_pydatetime(),
                "twin_state": estimate_groups.get(moment, []),
                "meter_kw": None
                if pd.isna(meter_series.iloc[index])
                else float(meter_series.iloc[index]),
                "cv_events": cv_groups.get(moment, []),
                "recommendations": [],
            }
            for index, moment in enumerate(moments)
        ]
