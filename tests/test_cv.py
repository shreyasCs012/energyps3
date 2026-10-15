from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from PIL import Image, ImageDraw

from contracts.models import EquipmentState
from cv.classifier import (
    TemporalSmoother,
    classify_features,
    fit_feature_classifier,
    predict_feature_classifier,
)
from cv.eval import evaluate_events
from cv.features import augment_frame, extract_frame_features
from cv.ingest_clips import ingest_manifest, load_manifest, split_source_clips
from cv.lights import detect_lights
from cv.stream import iter_video_frames, normalize_video, process_video
from renderer.render import render_frame, render_video
from replay.clip_selector import select_replay_clips


def _sample_timeline() -> pd.DataFrame:
    timestamp = pd.Timestamp("2025-01-01T00:00:00Z")
    return pd.DataFrame(
        [
            {
                "timestamp": timestamp + pd.Timedelta(minutes=minute),
                "equipment_id": "CNC-01",
                "state": state,
                "operator_present_true": minute == 1,
                "lights_on": True,
            }
            for minute, state in enumerate(("OFF", "RUNNING", "RUNNING"))
        ]
    )


def test_frame_features_state_classifier_and_temporal_hysteresis():
    image = Image.new("RGB", (32, 32), (15, 15, 15))
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 24, 24), fill=(0, 230, 80))
    features = extract_frame_features(image, None, {"x": 0, "y": 0, "width": 1, "height": 1})
    state, confidence = classify_features(features)
    assert state == EquipmentState.RUNNING and confidence > 0.6
    smoother = TemporalSmoother(window=3, votes=2)
    assert smoother.update(EquipmentState.IDLE) == EquipmentState.IDLE
    assert smoother.update(EquipmentState.RUNNING) == EquipmentState.IDLE
    assert smoother.update(EquipmentState.RUNNING) == EquipmentState.RUNNING
    augmented = augment_frame(image, brightness=0.8, horizontal_flip=True)
    assert augmented.size == image.size
    assert detect_lights(image, {"x": 0, "y": 0, "width": 1, "height": 1}, 0.1)[0]


def test_renderer_writes_mp4_and_frame_aligned_labels(tmp_path):
    pytest.importorskip("av")
    timeline = _sample_timeline()
    video = tmp_path / "sample.mp4"
    labels = tmp_path / "labels.csv"
    rendered = render_video(timeline, video, labels, fps=2, frame_size=(320, 180))
    assert video.is_file() and labels.is_file()
    assert len(rendered) == len(timeline)
    assert len(pd.read_csv(labels)) == len(timeline)
    import av

    with av.open(str(video)) as container:
        frames = list(container.decode(video=0))
    assert len(frames) == 3
    frame = render_frame(timeline, timeline.timestamp.iloc[0], frame_size=(320, 180))
    assert frame.size == (320, 180)


def test_stream_processor_emits_events_without_frame_artifacts(tmp_path):
    pytest.importorskip("av")
    video = tmp_path / "sample.mp4"
    render_video(_sample_timeline(), video, tmp_path / "labels.csv", fps=1, frame_size=(320, 180))
    config = {
        "machine_rois": {"CNC-01": {"x": 0, "y": 0, "width": 1, "height": 1}},
        "zone_rois": {},
        "smoothing_window": 1,
        "smoothing_votes": 1,
    }
    events = process_video(video, "cam-1", "CNC-01", config, clip_id="clip-1")
    assert len(events) == 3
    assert events.clip_id.eq("clip-1").all()
    assert set(events.state).issubset({state.value for state in EquipmentState})
    assert list(tmp_path.glob("*.jpg")) == []
    augmented = process_video(video, "cam-1", "CNC-01", config, clip_id="train", augment=True)
    assert len(augmented) == 15


def test_clip_normalization_uses_uniform_resolution_and_cadence(tmp_path):
    pytest.importorskip("av")
    source = tmp_path / "source.mp4"
    render_video(_sample_timeline(), source, tmp_path / "labels.csv", fps=2)
    normalized = normalize_video(source, tmp_path / "normalized.mp4", fps=10, seed=5)
    frames = list(iter_video_frames(normalized))
    assert len(frames) == 15
    assert all(frame.size == (640, 360) for _, frame in frames)


def test_manifest_ingest_normalizes_then_augments_training_clips_only(tmp_path):
    pytest.importorskip("av")
    source = tmp_path / "source.mp4"
    render_video(_sample_timeline(), source, tmp_path / "source-labels.csv", fps=1)
    rows = []
    for clip_id in ("a", "b", "c"):
        clip_path = tmp_path / f"{clip_id}.mp4"
        clip_path.write_bytes(source.read_bytes())
        rows.append(
            {
                "clip_id": clip_id,
                "path": clip_path.name,
                "machine_type": "cnc",
                "label_state": "RUNNING",
                "operator_present": False,
                "lights_on": True,
                "source": "procedural",
                "duration_s": 3,
                "notes": "generated test clip",
            }
        )
    manifest_path = tmp_path / "manifest.csv"
    pd.DataFrame(rows).to_csv(manifest_path, index=False)
    split_manifest, events = ingest_manifest(
        manifest_path,
        output_path=tmp_path / "events.parquet",
        seed=3,
        normalized_dir=tmp_path / "normalized",
    )
    assert set(split_manifest.split) == {"train", "validation", "test"}
    training_clip = split_manifest.loc[split_manifest.split == "train", "clip_id"].iloc[0]
    assert events.loc[events.clip_id == training_clip, "augmentation_id"].nunique() == 5
    assert len(list((tmp_path / "normalized").glob("*.mp4"))) == 3
    assert list(tmp_path.glob("*.jpg")) == []


def test_manifest_split_is_by_source_clip_and_replay_falls_back(tmp_path):
    rows = []
    for index in range(8):
        path = tmp_path / f"clip-{index}.mp4"
        path.touch()
        rows.append(
            {
                "clip_id": f"clip-{index}",
                "path": path.name,
                "machine_type": "cnc",
                "label_state": "RUNNING" if index % 2 else "IDLE",
                "operator_present": True,
                "lights_on": True,
                "source": "procedural" if index % 2 else "real",
                "duration_s": 10,
                "notes": "test",
            }
        )
    manifest_path = tmp_path / "manifest.csv"
    pd.DataFrame(rows).to_csv(manifest_path, index=False)
    manifest = split_source_clips(load_manifest(manifest_path), seed=5)
    assert manifest.groupby("clip_id").split.nunique().max() == 1
    assert set(manifest.split) == {"train", "validation", "test"}
    timestamp = datetime(2025, 1, 1, tzinfo=UTC)
    timeline = pd.DataFrame(
        {
            "timestamp": [timestamp, timestamp + timedelta(minutes=1)],
            "equipment_id": ["CNC-01", "CNC-01"],
            "state": ["RUNNING", "FAULT"],
        }
    )
    clips = pd.DataFrame(
        [{"path": "run.mp4", "label_state": "RUNNING", "duration_s": 5, "machine_type": "cnc"}]
    )
    mapping = select_replay_clips(timeline, clips, "fallback.mp4")
    assert mapping.iloc[0].clip_path == "run.mp4"
    assert mapping.iloc[1].fallback and mapping.iloc[1].transition


def test_cv_evaluator_reports_held_out_clip_sources_and_classes():
    manifest = pd.DataFrame(
        [
            {"clip_id": "tr", "label_state": "RUNNING", "source": "procedural", "split": "train"},
            {"clip_id": "te", "label_state": "IDLE", "source": "real", "split": "test"},
        ]
    )
    events = pd.DataFrame(
        [
            {"clip_id": "tr", "state": "RUNNING", "split": "train"},
            {"clip_id": "te", "state": "IDLE", "split": "test"},
        ]
    )
    report = evaluate_events(events, manifest)
    assert report["split_unit"] == "source_clip"
    assert report["heldout_samples"] == 1
    assert report["real"]["confusion_matrix"][2][2] == 1


def test_visual_random_forest_uses_training_clips_only():
    rows = []
    for clip_index, state in enumerate(("OFF", "STANDBY", "IDLE", "RUNNING")):
        for sample in range(5):
            rows.append(
                {
                    "motion_energy": sample / 10 if state == "RUNNING" else 0.0,
                    "green_fraction": 0.1 if state == "RUNNING" else 0.0,
                    "amber_fraction": 0.1 if state == "IDLE" else 0.0,
                    "red_fraction": 0.0,
                    "panel_brightness": 0.5 if state != "OFF" else 0.0,
                    "label_state": state,
                    "clip_id": f"train-{clip_index}",
                    "split": "train",
                }
            )
    model = fit_feature_classifier(pd.DataFrame(rows), seed=9)
    predictions = predict_feature_classifier(model, pd.DataFrame(rows[:4]))
    assert len(predictions) == 4
    assert all(0 <= result["confidence"] <= 1 for result in predictions)
