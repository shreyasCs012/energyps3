"""Streaming video decode and per-second CV event production."""

from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from PIL import Image

from cv.classifier import TemporalSmoother, classify_features
from cv.features import augmentation_variants, extract_frame_features
from cv.lights import detect_lights
from cv.person import detect_people


def iter_video_frames(
    path: str | Path, target_size: tuple[int, int] = (640, 360)
) -> Iterator[tuple[float, Image.Image]]:
    """Decode and normalize frames as a stream; no frame files are written."""
    try:
        import av
    except ImportError:
        av = None
    if av is not None:
        with av.open(str(path)) as container:
            stream = container.streams.video[0]
            rate = float(stream.average_rate) if stream.average_rate else 1.0
            for index, frame in enumerate(container.decode(stream)):
                seconds = (
                    float(frame.pts * frame.time_base) if frame.pts is not None else index / rate
                )
                image = (
                    frame.to_image().convert("RGB").resize(target_size, Image.Resampling.LANCZOS)
                )
                yield seconds, image
        return
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - requires optional decoder
        raise RuntimeError(
            "video decoding requires PyAV or OpenCV; install the project 'cv' extra"
        ) from exc
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise ValueError(f"could not open video: {path}")
    try:
        while True:
            ok, bgr = capture.read()
            if not ok:
                break
            seconds = float(capture.get(cv2.CAP_PROP_POS_MSEC) / 1000)
            rgb = cv2.cvtColor(cv2.resize(bgr, target_size), cv2.COLOR_BGR2RGB)
            yield seconds, Image.fromarray(rgb)
    finally:
        capture.release()


def normalize_video(
    source_path: str | Path,
    output_path: str | Path,
    fps: int = 10,
    resolution: tuple[int, int] = (640, 360),
    bitrate: int = 1_200_000,
    grain_sigma: float = 0.8,
    seed: int = 42,
) -> Path:
    """Transcode a clip to a uniform MPEG-4 profile while streaming frames in memory."""
    try:
        import av
    except ImportError as exc:  # pragma: no cover - requires optional decoder
        raise RuntimeError(
            "clip normalization requires PyAV; install the project 'cv' extra"
        ) from exc
    if fps < 1 or bitrate < 1 or grain_sigma < 0 or min(resolution) < 1:
        raise ValueError("fps, bitrate, and resolution must be positive; grain cannot be negative")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    input_container = av.open(str(source_path))
    output_container = av.open(str(output_path), mode="w")
    stream = output_container.add_stream("mpeg4", rate=fps)
    stream.width, stream.height = resolution
    stream.pix_fmt = "yuv420p"
    stream.bit_rate = bitrate
    next_sample = 0.0
    first_seconds: float | None = None
    last_seconds = 0.0
    last_image: Image.Image | None = None

    def encode_image(image: Image.Image) -> None:
        pixels = np.asarray(image, dtype=float)
        if grain_sigma:
            pixels = np.clip(pixels + rng.normal(0, grain_sigma, pixels.shape), 0, 255)
        normalized = Image.fromarray(pixels.astype(np.uint8))
        output_frame = av.VideoFrame.from_ndarray(np.asarray(normalized), format="rgb24")
        for packet in stream.encode(output_frame):
            output_container.mux(packet)

    try:
        input_stream = input_container.streams.video[0]
        source_rate = float(input_stream.average_rate) if input_stream.average_rate else float(fps)
        for index, frame in enumerate(input_container.decode(input_stream)):
            source_seconds = (
                float(frame.pts * frame.time_base) if frame.pts is not None else index / source_rate
            )
            if first_seconds is None:
                first_seconds = source_seconds
            seconds = source_seconds - first_seconds
            image = frame.to_image().convert("RGB").resize(resolution, Image.Resampling.LANCZOS)
            if last_image is None:
                last_image = image
                encode_image(last_image)
                next_sample = 1.0 / fps
            else:
                while next_sample < seconds - 1e-6:
                    encode_image(last_image)
                    next_sample += 1.0 / fps
                last_image = image
                if seconds + 1e-6 >= next_sample:
                    encode_image(last_image)
                    next_sample += 1.0 / fps
            last_seconds = seconds
        if last_image is not None:
            end_seconds = last_seconds + 1.0 / source_rate
            while next_sample < end_seconds - 1e-6:
                encode_image(last_image)
                next_sample += 1.0 / fps
        for packet in stream.encode():
            output_container.mux(packet)
    finally:
        input_container.close()
        output_container.close()
    return output_path


def process_video(
    path: str | Path,
    camera_id: str,
    machine_id: str | None,
    config: Mapping[str, Any],
    clip_id: str | None = None,
    start_timestamp: object = "1970-01-01T00:00:00Z",
    station_roi: Mapping[str, float] | None = None,
    yolo_model: object | None = None,
    augment: bool = False,
) -> pd.DataFrame:
    """Process video at 1 Hz, emit events, and discard each decoded frame immediately."""
    machine_rois = config.get("machine_rois", {})
    zones = config.get("zone_rois", {})
    roi = station_roi or machine_rois.get(machine_id, {"x": 0, "y": 0, "width": 1, "height": 1})
    thresholds = config.get("classifier", {})
    smoothers: dict[int, TemporalSmoother] = {}
    prior_frames: dict[int, Image.Image] = {}
    start = pd.Timestamp(start_timestamp)
    next_sample_second = -1.0
    events = []
    for seconds, frame in iter_video_frames(path):
        if seconds + 1e-6 < next_sample_second:
            continue
        next_sample_second = seconds + 1.0
        variants = augmentation_variants(frame) if augment else [frame]
        light_values = [
            detect_lights(frame, zone, float(config.get("light_threshold", 0.52)))
            for zone in zones.values()
        ]
        presence = detect_people(
            frame, config.get("station_rois", {}).get(machine_id), yolo_model=yolo_model
        )
        for augmentation_id, variant in enumerate(variants):
            smoother = smoothers.setdefault(
                augmentation_id,
                TemporalSmoother(
                    window=int(config.get("smoothing_window", 5)),
                    votes=int(config.get("smoothing_votes", 3)),
                ),
            )
            features = extract_frame_features(variant, prior_frames.get(augmentation_id), roi)
            state, confidence = classify_features(features, thresholds)
            state = smoother.update(state)
            if machine_id is not None:
                events.append(
                    {
                        "timestamp": start + pd.Timedelta(seconds=seconds),
                        "event_id": f"{clip_id or camera_id}-{len(events):06d}",
                        "camera_id": camera_id,
                        "machine_id": machine_id,
                        "zone_id": None,
                        "state": state.value,
                        "operator_present": presence["present"],
                        "presence_confidence": presence["confidence"],
                        "lights_on": any(value[0] for value in light_values),
                        "confidence": confidence,
                        "clip_id": clip_id,
                        "augmentation_id": augmentation_id,
                    }
                )
            prior_frames[augmentation_id] = variant
        for zone_index, (zone_id, zone_roi) in enumerate(zones.items()):
            is_on, luminance = detect_lights(
                frame, zone_roi, float(config.get("light_threshold", 0.52))
            )
            events.append(
                {
                    "timestamp": start + pd.Timedelta(seconds=seconds),
                    "event_id": f"{clip_id or camera_id}-zone-{zone_index}-{len(events):06d}",
                    "camera_id": camera_id,
                    "machine_id": None,
                    "zone_id": str(zone_id),
                    "state": None,
                    "operator_present": presence["present"],
                    "presence_confidence": 0.0,
                    "lights_on": is_on,
                    "confidence": min(
                        0.99, 0.65 + abs(luminance - float(config.get("light_threshold", 0.52)))
                    ),
                    "clip_id": clip_id,
                    "augmentation_id": 0,
                }
            )
    return pd.DataFrame(
        events,
        columns=[
            "timestamp",
            "event_id",
            "camera_id",
            "machine_id",
            "zone_id",
            "state",
            "operator_present",
            "presence_confidence",
            "lights_on",
            "confidence",
            "clip_id",
            "augmentation_id",
        ],
    )
