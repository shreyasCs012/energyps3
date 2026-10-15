"""Read plant nameplate configuration as the twin's initial parameter estimates."""

from pathlib import Path
from typing import Any

import yaml

from twin.model import MachineParameters


def load_twin_config(path: str | Path) -> tuple[dict[str, MachineParameters], dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as stream:
        value = yaml.safe_load(stream)
    machines = {
        item["id"]: MachineParameters(
            equipment_id=item["id"],
            p_run_kw=float(item["p_run_kw"]),
            p_idle_kw=float(item["p_idle_kw"]),
            p_standby_kw=float(item["p_standby_kw"]),
            warmup_min=int(item["warmup_min"]),
            restart_kwh=float(item["restart_kwh"]),
            min_off_min=int(item["min_off_min"]),
            min_on_min=int(item["min_on_min"]),
            needs=tuple(item.get("needs", [])),
            submetered=bool(item.get("submetered", False)),
        )
        for item in value["machines"]
    }
    return machines, value
