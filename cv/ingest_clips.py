"""Validate clip manifests, split by source clip, and stream CV event extraction."""

from pathlib import Path

import pandas as pd
import yaml

from cv.stream import normalize_video, process_video

REQUIRED_MANIFEST_COLUMNS = {
    "clip_id",
    "path",
    "machine_type",
    "label_state",
    "operator_present",
    "lights_on",
    "source",
    "duration_s",
    "notes",
}
VALID_SOURCES = {"higgsfield", "runway", "real", "procedural"}
VALID_STATES = {"OFF", "STANDBY", "IDLE", "RUNNING"}


def load_manifest(path: str | Path) -> pd.DataFrame:
    """Read and validate the documented `data/clips/manifest.csv` schema."""
    path = Path(path)
    manifest = pd.read_csv(path)
    missing = REQUIRED_MANIFEST_COLUMNS - set(manifest.columns)
    if missing:
        raise ValueError(f"clip manifest is missing columns: {sorted(missing)}")
    if manifest.clip_id.isna().any() or manifest.clip_id.duplicated().any():
        raise ValueError("clip_id values must be present and unique")
    if not set(manifest.source.dropna().unique()).issubset(VALID_SOURCES):
        raise ValueError(f"source must be one of {sorted(VALID_SOURCES)}")
    if not set(manifest.label_state.dropna().str.upper().unique()).issubset(VALID_STATES):
        raise ValueError(f"label_state must be one of {sorted(VALID_STATES)}")
    durations = pd.to_numeric(manifest.duration_s, errors="coerce")
    if durations.isna().any() or (durations <= 0).any():
        raise ValueError("duration_s must be positive")
    manifest["resolved_path"] = manifest.path.map(
        lambda value: str((path.parent / str(value)).resolve())
    )
    missing_paths = [value for value in manifest.resolved_path if not Path(value).is_file()]
    if missing_paths:
        raise FileNotFoundError(f"clip files do not exist: {missing_paths[:3]}")
    return manifest


def split_source_clips(
    manifest: pd.DataFrame,
    seed: int = 42,
    train_fraction: float = 0.7,
    validation_fraction: float = 0.15,
) -> pd.DataFrame:
    """Assign whole source clips to splits before any frame extraction or augmentation."""
    if not 0 < train_fraction < 1 or not 0 < validation_fraction < 1:
        raise ValueError("split fractions must be between zero and one")
    if train_fraction + validation_fraction >= 1:
        raise ValueError("train and validation fractions must sum to less than one")
    clip_ids = sorted(manifest.clip_id.astype(str).unique())
    if len(clip_ids) < 3:
        raise ValueError(
            "at least three distinct source clips are required for train/validation/test"
        )
    import numpy as np

    shuffled = np.random.default_rng(seed).permutation(clip_ids).tolist()
    train_count = max(1, int(len(shuffled) * train_fraction))
    validation_count = max(1, int(len(shuffled) * validation_fraction))
    if train_count + validation_count >= len(shuffled):
        train_count = len(shuffled) - 2
        validation_count = 1
    split_by_id = {
        **dict.fromkeys(shuffled[:train_count], "train"),
        **dict.fromkeys(shuffled[train_count : train_count + validation_count], "validation"),
        **dict.fromkeys(shuffled[train_count + validation_count :], "test"),
    }
    result = manifest.copy()
    result["split"] = result.clip_id.astype(str).map(split_by_id)
    return result


def ingest_manifest(
    manifest_path: str | Path,
    cv_config_path: str | Path = "config/cv.yaml",
    output_path: str | Path | None = None,
    seed: int = 42,
    normalized_dir: str | Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Stream clips into minute/second events and return split manifest plus events."""
    manifest = split_source_clips(load_manifest(manifest_path), seed=seed)
    config = yaml.safe_load(Path(cv_config_path).read_text(encoding="utf-8"))
    normalization = config.get("normalization", {})
    normalized_root = (
        Path(normalized_dir)
        if normalized_dir is not None
        else Path(manifest_path).parent / "normalized"
    )
    all_events = []
    for row in manifest.itertuples():
        normalized_path = normalized_root / f"{row.clip_id}.mp4"
        normalize_video(
            row.resolved_path,
            normalized_path,
            fps=int(normalization.get("fps", 10)),
            resolution=tuple(normalization.get("resolution", [640, 360])),
            bitrate=int(normalization.get("bitrate", 1_200_000)),
            grain_sigma=float(normalization.get("synthetic_grain_sigma", 0.8)),
            seed=seed + sum(str(row.clip_id).encode("utf-8")),
        )
        machine_id = getattr(row, "machine_id", None)
        if machine_id is not None and pd.isna(machine_id):
            machine_id = None
        zone_id = getattr(row, "zone_id", None)
        if zone_id is not None and pd.isna(zone_id):
            zone_id = None
        if machine_id is None and zone_id is None:
            machine_id = f"clip-{row.clip_id}"
        camera_config = dict(config)
        camera_config["zone_rois"] = (
            {str(zone_id): config.get("zone_rois", {})[str(zone_id)]} if zone_id is not None else {}
        )
        events = process_video(
            normalized_path,
            camera_id=f"clip-{row.clip_id}",
            machine_id=machine_id,
            config=camera_config,
            clip_id=str(row.clip_id),
            augment=bool(config.get("augmentation", {}).get("enabled", False))
            and row.split == "train",
        )
        events["label_state"] = str(row.label_state).upper()
        events["source"] = row.source
        events["split"] = row.split
        all_events.append(events)
    result = pd.concat(all_events, ignore_index=True) if all_events else pd.DataFrame()
    if output_path is not None:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        result.to_parquet(output, index=False)
    return manifest, result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="data/clips/manifest.csv")
    parser.add_argument("--config", default="config/cv.yaml")
    parser.add_argument("--output", default="data/generated/cv_events.parquet")
    parser.add_argument("--normalized-dir", default="data/clips/normalized")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    split_manifest, events = ingest_manifest(
        args.manifest, args.config, args.output, args.seed, args.normalized_dir
    )
    print(f"Processed {split_manifest.clip_id.nunique()} source clips into {len(events)} events")


if __name__ == "__main__":
    main()
