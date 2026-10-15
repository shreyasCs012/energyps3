"""P1 threshold policy: alerts only, no equipment controls."""

from pathlib import Path

import pandas as pd
import yaml

from policies.models import PolicyAlert, PolicyDecision


def evaluate(main_meter: pd.DataFrame, threshold_kw: float | None = None) -> PolicyDecision:
    if threshold_kw is None:
        config = yaml.safe_load(Path("config/policies.yaml").read_text(encoding="utf-8"))
        threshold_kw = float(config["threshold_alert"]["main_meter_kw"])
    if threshold_kw <= 0:
        raise ValueError("threshold_kw must be positive")
    if main_meter.empty or not {"interval_start", "main_kw"}.issubset(main_meter.columns):
        return PolicyDecision()
    alerts = [
        PolicyAlert(
            timestamp=row.interval_start,
            rule="main_meter_threshold",
            message=f"Main-meter demand exceeded the configured {threshold_kw:g} kW threshold.",
            evidence={"main_kw": float(row.main_kw), "threshold_kw": float(threshold_kw)},
        )
        for row in main_meter.itertuples()
        if float(row.main_kw) > threshold_kw
    ]
    return PolicyDecision(alerts=alerts)
