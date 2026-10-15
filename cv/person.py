"""Optional person detection using Ultralytics YOLO or OpenCV's HOG people model."""

from collections.abc import Mapping

import numpy as np
from PIL import Image

from cv.features import crop_roi


def detect_people(
    frame: np.ndarray | Image.Image,
    roi: Mapping[str, float] | None = None,
    backend: str = "auto",
    yolo_model: object | None = None,
) -> dict[str, object]:
    """Detect people within a station ROI without saving or returning the image.

    YOLO requires a caller-provided model to avoid implicit network weight downloads.
    HOG is the deterministic offline fallback when OpenCV is installed.
    """
    if backend not in {"auto", "yolo", "hog"}:
        raise ValueError("backend must be auto, yolo, or hog")
    image = (
        frame
        if isinstance(frame, Image.Image)
        else Image.fromarray(np.asarray(frame).astype(np.uint8))
    )
    if roi is not None:
        image = crop_roi(image, roi)
    if backend in {"auto", "yolo"} and yolo_model is not None:
        result = yolo_model(image, verbose=False)[0]
        boxes = getattr(result, "boxes", None)
        count = len(boxes) if boxes is not None else 0
        confidence = (
            float(max(boxes.conf.tolist()))
            if count and getattr(boxes, "conf", None) is not None
            else 0.0
        )
        return {"present": count > 0, "count": count, "confidence": confidence, "backend": "yolo"}
    if backend == "yolo":
        raise ValueError("YOLO backend requires a caller-provided model; no weights are downloaded")
    try:
        import cv2
    except ImportError:
        if backend == "hog":
            raise RuntimeError(
                "HOG presence detection requires OpenCV; install the project 'cv' extra"
            ) from None
        return {"present": None, "count": None, "confidence": 0.0, "backend": "unavailable"}
    detector = cv2.HOGDescriptor()
    detector.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
    rgb = np.asarray(image.convert("RGB"))
    boxes, weights = detector.detectMultiScale(rgb, winStride=(8, 8), padding=(8, 8), scale=1.05)
    confidence = float(np.max(weights)) if len(weights) else 0.0
    return {
        "present": bool(len(boxes)),
        "count": int(len(boxes)),
        "confidence": float(np.clip(confidence, 0, 1)),
        "backend": "hog",
    }
