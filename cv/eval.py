"""Source-clip-level state classifier evaluation with domain-separated reports."""

from typing import Any

import pandas as pd
from sklearn.metrics import classification_report, confusion_matrix

STATE_LABELS = ["OFF", "STANDBY", "IDLE", "RUNNING"]


def evaluate_events(events: pd.DataFrame, manifest: pd.DataFrame) -> dict[str, Any]:
    """Score held-out event states per class, separately for procedural and AI clips."""
    required_events = {"clip_id", "state", "split"}
    if not required_events.issubset(events.columns):
        raise ValueError(f"events must contain {sorted(required_events)}")
    if not {"clip_id", "label_state", "source", "split"}.issubset(manifest.columns):
        raise ValueError("split manifest must include clip_id, label_state, source, and split")
    train_ids = set(manifest.loc[manifest.split == "train", "clip_id"].astype(str))
    test_ids = set(manifest.loc[manifest.split == "test", "clip_id"].astype(str))
    if train_ids & test_ids:
        raise ValueError("source clip leakage: train and test clip IDs overlap")
    heldout = events[events.split == "test"].copy()
    heldout = heldout.merge(
        manifest.loc[:, ["clip_id", "label_state", "source"]],
        on="clip_id",
        how="left",
        validate="many_to_one",
    )
    heldout["state"] = heldout.state.astype(str).str.upper()
    heldout["label_state"] = heldout.label_state.astype(str).str.upper()

    def score(frame: pd.DataFrame) -> dict[str, Any]:
        if frame.empty:
            return {"samples": 0, "classification_report": {}, "confusion_matrix": []}
        return {
            "samples": int(len(frame)),
            "classification_report": classification_report(
                frame.label_state,
                frame.state,
                labels=STATE_LABELS,
                output_dict=True,
                zero_division=0,
            ),
            "confusion_matrix": confusion_matrix(
                frame.label_state, frame.state, labels=STATE_LABELS
            ).tolist(),
        }

    by_source = {str(source): score(group) for source, group in heldout.groupby("source")}
    return {
        "split_unit": "source_clip",
        "heldout_samples": int(len(heldout)),
        "procedural": score(heldout[heldout.source == "procedural"]),
        "ai_generated": score(heldout[heldout.source.isin(["higgsfield", "runway"])]),
        "real": score(heldout[heldout.source == "real"]),
        "by_source": by_source,
    }
