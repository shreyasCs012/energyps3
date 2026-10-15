"""Procedurally render a plant state timeline without storing source frames."""

from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

DEFAULT_LAYOUT = {
    "CNC-01": (160, 170),
    "CNC-02": (360, 170),
    "C2": (560, 170),
    "HP1": (760, 170),
    "CV1": (460, 380),
}
STATE_COLORS = {
    "OFF": (65, 72, 78),
    "STANDBY": (80, 150, 210),
    "WARMUP": (240, 183, 60),
    "IDLE": (236, 155, 50),
    "RUNNING": (57, 184, 104),
    "FAULT": (220, 62, 62),
    "MAINTENANCE": (160, 115, 190),
}


def render_frame(
    timeline: pd.DataFrame,
    timestamp: object,
    frame_size: tuple[int, int] = (960, 540),
    lights_on: bool | None = None,
    zone_lights: Mapping[str, bool] | None = None,
) -> Image.Image:
    """Render one labeled floor-plan frame from the nearest timeline timestamp."""
    required = {"timestamp", "equipment_id", "state"}
    if not required.issubset(timeline.columns):
        raise ValueError(f"timeline must contain {sorted(required)}")
    instant = pd.Timestamp(timestamp)
    current = timeline.copy()
    current["timestamp"] = pd.to_datetime(current.timestamp)
    rows = current[current.timestamp == instant]
    if rows.empty:
        raise ValueError(f"no equipment rows found at {instant.isoformat()}")
    width, height = 960, 540
    light_state = bool(lights_on) if lights_on is not None else _lights_for_frame(rows)
    background = (38, 44, 50) if light_state else (20, 24, 29)
    image = Image.new("RGB", frame_size, background)
    draw = ImageDraw.Draw(image, "RGBA")
    zone_lights = zone_lights or dict.fromkeys(("Z1", "Z2", "Z3"), light_state)
    _draw_floor(draw, width, height, light_state, zone_lights)
    machine_rows = {str(row.equipment_id): row for row in rows.itertuples()}
    for machine_id, (x, y) in DEFAULT_LAYOUT.items():
        row = machine_rows.get(machine_id)
        if row is None:
            continue
        state = str(row.state)
        color = STATE_COLORS.get(state, STATE_COLORS["OFF"])
        _draw_machine(draw, machine_id, state, color, x, y, instant.minute)
        if bool(getattr(row, "operator_present_true", getattr(row, "operator_present", False))):
            _draw_operator(draw, x + 58, y + 52)
    draw.rectangle((20, 18, width - 20, 54), fill=(12, 18, 22, 220))
    draw.text(
        (32, 27),
        f"SYNTHETIC PLANT  |  {instant.isoformat()}  |  "
        f"{'LIGHTS ON' if light_state else 'LIGHTS OFF'}",
        fill="white",
        font=ImageFont.load_default(),
    )
    if frame_size != (width, height):
        image = image.resize(frame_size, Image.Resampling.LANCZOS)
    return image


def _lights_for_frame(rows: pd.DataFrame) -> bool:
    if "lights_on" in rows:
        return bool(rows.lights_on.astype(bool).any())
    return True


def _draw_floor(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    lights_on: bool,
    zone_lights: Mapping[str, bool],
) -> None:
    floor_color = (122, 127, 124, 255) if lights_on else (48, 54, 58, 255)
    draw.rounded_rectangle((28, 70, width - 28, height - 28), radius=18, fill=floor_color)
    draw.line((40, 285, width - 40, 285), fill=(220, 211, 150, 130), width=2)
    draw.rectangle((48, 82, width - 48, 270), outline=(232, 226, 205, 150), width=2)
    draw.rectangle((48, 300, width - 48, height - 42), outline=(232, 226, 205, 150), width=2)
    zones = {
        "Z1": (50, 100, 340, 268),
        "Z2": (380, 100, width - 50, 268),
        "Z3": (50, 320, width - 50, height - 45),
    }
    for zone_id, bounds in zones.items():
        overlay = (255, 238, 170, 45) if zone_lights.get(zone_id, lights_on) else (0, 0, 0, 120)
        draw.rectangle(bounds, fill=overlay, outline=(240, 233, 188, 150), width=1)
        draw.text((bounds[0] + 4, bounds[1] + 4), zone_id, fill=(245, 245, 230, 230))
    draw.text((54, 88), "MACHINING BAY", fill=(20, 30, 32, 255))
    draw.text((54, 306), "ASSEMBLY / CONVEYOR", fill=(20, 30, 32, 255))


def _draw_machine(
    draw: ImageDraw.ImageDraw,
    machine_id: str,
    state: str,
    color: tuple[int, int, int],
    x: int,
    y: int,
    minute: int,
) -> None:
    draw.rounded_rectangle(
        (x - 65, y - 45, x + 65, y + 50), radius=10, fill=(42, 50, 56, 255), outline=color, width=4
    )
    draw.rectangle((x - 43, y - 28, x + 42, y + 20), fill=(82, 97, 101, 255))
    if state == "RUNNING":
        # Spindle/press motion is deterministic and tied to simulation time.
        angle = (minute * 27) % 360
        radians = np.deg2rad(angle)
        dx, dy = int(14 * np.cos(radians)), int(14 * np.sin(radians))
        draw.ellipse((x - 14, y - 17, x + 14, y + 11), outline=(180, 225, 230, 255), width=3)
        draw.line((x - dx, y - 3 - dy, x + dx, y - 3 + dy), fill=(255, 232, 120, 255), width=3)
    elif state == "IDLE":
        draw.rectangle((x - 15, y - 10, x + 15, y + 4), fill=(230, 175, 62, 220))
    elif state == "STANDBY":
        draw.rectangle((x - 15, y - 10, x + 15, y + 4), fill=(85, 150, 205, 170))
    if machine_id == "CV1":
        for stripe in range(5):
            offset = (minute * 5 + stripe * 22) % 100 if state == "RUNNING" else stripe * 22
            draw.line(
                (x - 48 + offset % 96, y + 2, x - 40 + offset % 96, y + 18),
                fill=(245, 209, 90, 255),
                width=4,
            )
    draw.ellipse((x + 47, y - 43, x + 61, y - 29), fill=color)
    power_text = machine_id
    draw.text(
        (x - 29, y + 27), f"{power_text} · {state}", fill="white", font=ImageFont.load_default()
    )


def _draw_operator(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    draw.ellipse((x - 6, y - 19, x + 6, y - 7), fill=(241, 198, 158, 255))
    draw.rounded_rectangle((x - 8, y - 7, x + 8, y + 18), radius=4, fill=(46, 93, 170, 255))
    draw.line((x - 6, y + 17, x - 10, y + 28), fill=(27, 31, 37, 255), width=3)
    draw.line((x + 6, y + 17, x + 10, y + 28), fill=(27, 31, 37, 255), width=3)


def render_video(
    timeline: pd.DataFrame,
    video_path: str | Path,
    labels_path: str | Path,
    fps: int = 2,
    frame_size: tuple[int, int] = (960, 540),
) -> pd.DataFrame:
    """Stream-render frames to MP4 and write frame-accurate synthetic labels to CSV."""
    if fps < 1:
        raise ValueError("fps must be at least one")
    try:
        import av
    except ImportError as exc:  # pragma: no cover - depends on optional video extra
        raise RuntimeError("MP4 rendering requires PyAV; install the project 'cv' extra") from exc
    required = {"timestamp", "equipment_id", "state"}
    if not required.issubset(timeline.columns):
        raise ValueError(f"timeline must contain {sorted(required)}")
    ordered = timeline.copy()
    ordered["timestamp"] = pd.to_datetime(ordered.timestamp)
    timestamps = pd.DatetimeIndex(ordered.timestamp.drop_duplicates().sort_values())
    video_path = Path(video_path)
    labels_path = Path(labels_path)
    video_path.parent.mkdir(parents=True, exist_ok=True)
    labels_path.parent.mkdir(parents=True, exist_ok=True)
    labels = ordered.loc[
        :,
        [
            column
            for column in (
                "timestamp",
                "equipment_id",
                "state",
                "operator_present_true",
                "lights_on",
            )
            if column in ordered
        ],
    ].copy()
    labels.to_csv(labels_path, index=False)
    grouped_frames = {
        pd.Timestamp(timestamp): group
        for timestamp, group in ordered.groupby("timestamp", sort=True)
    }
    container = av.open(str(video_path), mode="w")
    stream = container.add_stream("mpeg4", rate=fps)
    stream.width, stream.height = frame_size
    stream.pix_fmt = "yuv420p"
    try:
        for timestamp in timestamps:
            image = render_frame(grouped_frames[timestamp], timestamp, frame_size)
            frame = av.VideoFrame.from_ndarray(np.asarray(image), format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    finally:
        container.close()
    return labels
