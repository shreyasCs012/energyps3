"""Frame features computed in memory; raw frames are never persisted."""

from collections.abc import Mapping

import numpy as np
from PIL import Image


def crop_roi(frame: np.ndarray | Image.Image, roi: Mapping[str, float]) -> Image.Image:
    """Crop a normalized ``{x,y,width,height}`` region from an RGB frame."""
    image = (
        frame
        if isinstance(frame, Image.Image)
        else Image.fromarray(np.asarray(frame).astype(np.uint8))
    )
    width, height = image.size
    x = int(float(roi["x"]) * width)
    y = int(float(roi["y"]) * height)
    right = int((float(roi["x"]) + float(roi["width"])) * width)
    bottom = int((float(roi["y"]) + float(roi["height"])) * height)
    if x < 0 or y < 0 or right > width or bottom > height or right <= x or bottom <= y:
        raise ValueError("ROI must be a non-empty normalized rectangle inside the frame")
    return image.convert("RGB").crop((x, y, right, bottom))


def extract_frame_features(
    frame: np.ndarray | Image.Image,
    previous_frame: np.ndarray | Image.Image | None,
    roi: Mapping[str, float],
) -> dict[str, float]:
    """Extract ROI motion energy, HSV stack-light fractions, and panel brightness."""
    current = crop_roi(frame, roi)
    rgb = np.asarray(current, dtype=np.uint8)
    hsv = np.asarray(current.convert("HSV"), dtype=np.uint8)
    brightness = rgb.max(axis=2).astype(float)
    hue = hsv[:, :, 0]
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    vivid = (saturation >= 90) & (value >= 70)
    green = vivid & (hue >= 45) & (hue <= 115)
    amber = vivid & (hue >= 5) & (hue <= 38)
    red = vivid & ((hue <= 5) | (hue >= 245))
    motion = 0.0
    if previous_frame is not None:
        prior = np.asarray(crop_roi(previous_frame, roi).convert("L"), dtype=float)
        current_gray = np.asarray(current.convert("L"), dtype=float)
        if prior.shape == current_gray.shape:
            motion = float(np.mean(np.abs(current_gray - prior)) / 255.0)
    size = max(1, hsv.shape[0] * hsv.shape[1])
    return {
        "motion_energy": motion,
        "green_fraction": float(green.sum() / size),
        "amber_fraction": float(amber.sum() / size),
        "red_fraction": float(red.sum() / size),
        "panel_brightness": float(brightness.mean() / 255.0),
    }


def augment_frame(
    frame: Image.Image,
    brightness: float = 1.0,
    contrast: float = 1.0,
    horizontal_flip: bool = False,
    blur_radius: float = 0.0,
    crop_fraction: float = 0.0,
) -> Image.Image:
    """Apply deterministic frame augmentation for clip-level training experiments."""
    from PIL import ImageEnhance, ImageFilter, ImageOps

    if brightness <= 0 or contrast <= 0 or blur_radius < 0 or not 0 <= crop_fraction < 0.45:
        raise ValueError("invalid augmentation parameters")
    result = frame.convert("RGB")
    if crop_fraction:
        width, height = result.size
        dx, dy = int(width * crop_fraction), int(height * crop_fraction)
        result = result.crop((dx, dy, width - dx, height - dy)).resize((width, height))
    if horizontal_flip:
        result = ImageOps.mirror(result)
    result = ImageEnhance.Brightness(result).enhance(brightness)
    result = ImageEnhance.Contrast(result).enhance(contrast)
    if blur_radius:
        result = result.filter(ImageFilter.GaussianBlur(blur_radius))
    return result


def augmentation_variants(frame: Image.Image) -> list[Image.Image]:
    """Create deterministic in-memory appearance variants after source-clip splitting."""
    return [
        frame.copy(),
        augment_frame(frame, brightness=0.85, contrast=1.15),
        augment_frame(frame, horizontal_flip=True),
        augment_frame(frame, blur_radius=1.0),
        augment_frame(frame, crop_fraction=0.08),
    ]
