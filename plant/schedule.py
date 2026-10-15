"""Deterministic daily production schedule generation."""

from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd

MACHINE_SETS = [
    ("CNC-01",),
    ("CNC-02", "C2"),
    ("HP1", "C2"),
    ("CV1",),
]


def generate_schedule(
    day: date, rng: np.random.Generator, short_shift: bool = False
) -> pd.DataFrame:
    """Create seeded, non-overlapping jobs per primary machine for one synthetic day."""
    rows: list[dict[str, object]] = []
    count = int(rng.integers(8, 15))
    shift_end = 18 if short_shift else 22
    machine_free: dict[str, int] = {key: 6 * 60 for key in ("CNC-01", "CNC-02", "HP1", "CV1")}
    for index in range(count):
        machines = MACHINE_SETS[int(rng.integers(0, len(MACHINE_SETS)))]
        primary = next(machine for machine in machines if machine != "C2")
        duration = int(rng.integers(120, 241))
        earliest = machine_free[primary]
        remaining = shift_end * 60 - earliest
        if remaining < 45:
            available = [name for name, free in machine_free.items() if shift_end * 60 - free >= 45]
            if not available:
                continue
            primary = str(rng.choice(available))
            machines = (primary, "C2") if primary in {"CNC-02", "HP1"} else (primary,)
            earliest = machine_free[primary]
            remaining = shift_end * 60 - earliest
        duration = min(duration, remaining)
        latest = max(earliest, shift_end * 60 - duration)
        start_minute = int(rng.integers(earliest, latest + 1)) if latest > earliest else earliest
        end_minute = start_minute + duration
        machine_free[primary] = end_minute + int(rng.integers(5, 26))
        start_dt = datetime.combine(day, time()) + timedelta(minutes=start_minute)
        end_dt = datetime.combine(day, time()) + timedelta(minutes=end_minute)
        rows.append(
            {
                "job_id": f"{day:%Y%m%d}-J{index + 1:02d}",
                "required_machines": ",".join(machines),
                "primary_machine": primary,
                "duration_min": end_minute - start_minute,
                "release_ts": start_dt - timedelta(minutes=int(rng.integers(0, 30))),
                "start_ts": start_dt,
                "end_ts": end_dt,
                "due_ts": end_dt + timedelta(minutes=int(rng.integers(15, 121))),
                "priority": int(rng.integers(1, 6)),
                "shiftable": bool(rng.random() < 0.45),
                "critical": bool(rng.random() < 0.15),
            }
        )
    return pd.DataFrame(rows).sort_values("start_ts", ignore_index=True)
