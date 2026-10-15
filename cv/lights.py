"""Zone light detection from ROI luminance."""

from collections.abc import Mapping

import numpy as np
from PIL import Image

from cv.features import crop_roi


def detect_lights(
    frame: np.ndarray | Image.Image,
    roi: Mapping[str, float],
    threshold: float = 0.52,
) -> tuple[bool, float]:
    """Return on/off and normalized mean luminance for a calibrated zone ROI."""
    if not 0 <= threshold <= 1:
        raise ValueError("threshold must be in [0, 1]")
    gray = np.asarray(crop_roi(frame, roi).convert("L"), dtype=float)
    luminance = float(gray.mean() / 255.0)
    return luminance >= threshold, luminance
