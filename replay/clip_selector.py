"""Deterministically select state-matched replay clips, with renderer fallback."""

from pathlib import Path

import pandas as pd

DEFAULT_MACHINE_TYPES = {
    "cnc-01": "cnc",
    "cnc-02": "cnc",
    "c2": "compressor",
    "cv1": "conveyor",
    "hp1": "press",
}


def select_replay_clips(
    timeline: pd.DataFrame,
    manifest: pd.DataFrame,
    renderer_fallback: str | Path,
    transition_seconds: float = 1.0,
    machine_types: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Map each equipment timestamp to a looping state clip and transition marker."""
    if not {"timestamp", "equipment_id", "state"}.issubset(timeline.columns):
        raise ValueError("timeline must contain timestamp, equipment_id, and state")
    if not {"path", "label_state", "duration_s"}.issubset(manifest.columns):
        raise ValueError("clip manifest must contain path, label_state, and duration_s")
    if transition_seconds < 0:
        raise ValueError("transition_seconds cannot be negative")
    clips = manifest.copy()
    clips["label_state"] = clips.label_state.astype(str).str.upper()
    lookup: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in clips.to_dict(orient="records"):
        machine_type = str(row.get("machine_type", "*")).lower()
        lookup.setdefault((machine_type, row["label_state"]), []).append(row)
    rows = timeline.copy()
    rows["timestamp"] = pd.to_datetime(rows.timestamp)
    rows = rows.sort_values(["equipment_id", "timestamp"])
    previous_state: dict[str, str] = {}
    previous_timestamp: dict[str, pd.Timestamp] = {}
    elapsed_by_equipment: dict[str, float] = {}
    clip_offsets: dict[tuple[str, str], int] = {}
    selections = []
    for event in rows.itertuples():
        equipment = str(event.equipment_id)
        state = str(event.state).upper()
        changed = previous_state.get(equipment) != state
        elapsed_by_equipment[equipment] = (
            0.0
            if changed
            else elapsed_by_equipment.get(equipment, 0.0)
            + max(0.0, (event.timestamp - previous_timestamp[equipment]).total_seconds())
        )
        machine_type = (machine_types or DEFAULT_MACHINE_TYPES).get(
            equipment.lower(), equipment.lower()
        )
        candidates = lookup.get((machine_type.lower(), state)) or lookup.get(("*", state), [])
        if candidates:
            key = (equipment, state)
            candidate = candidates[clip_offsets.get(key, 0) % len(candidates)]
            clip_offsets[key] = clip_offsets.get(key, 0) + (1 if changed else 0)
            duration = max(float(candidate["duration_s"]), 0.001)
            selections.append(
                {
                    "timestamp": event.timestamp,
                    "equipment_id": equipment,
                    "state": state,
                    "clip_path": str(candidate["path"]),
                    "clip_id": candidate.get("clip_id"),
                    "offset_seconds": elapsed_by_equipment[equipment] % duration,
                    "transition": bool(changed and equipment in previous_state),
                    "crossfade_seconds": transition_seconds if changed else 0.0,
                    "fallback": False,
                }
            )
        else:
            selections.append(
                {
                    "timestamp": event.timestamp,
                    "equipment_id": equipment,
                    "state": state,
                    "clip_path": str(renderer_fallback),
                    "clip_id": None,
                    "offset_seconds": elapsed_by_equipment[equipment],
                    "transition": bool(changed and equipment in previous_state),
                    "crossfade_seconds": transition_seconds if changed else 0.0,
                    "fallback": True,
                }
            )
        previous_state[equipment] = state
        previous_timestamp[equipment] = event.timestamp
    return pd.DataFrame(selections)
