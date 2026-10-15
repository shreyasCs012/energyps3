"""Rule-based state classifier with configurable N-of-M temporal hysteresis."""

from collections import deque
from collections.abc import Mapping

from sklearn.ensemble import RandomForestClassifier

from contracts.models import EquipmentState

FEATURE_COLUMNS = (
    "motion_energy",
    "green_fraction",
    "amber_fraction",
    "red_fraction",
    "panel_brightness",
)
ACTIVITY_STATES = ("OFF", "STANDBY", "IDLE", "RUNNING")


def classify_features(
    features: Mapping[str, float],
    thresholds: Mapping[str, float] | None = None,
) -> tuple[EquipmentState, float]:
    """Map motion, stack-light color, and panel brightness into a machine state."""
    thresholds = thresholds or {}
    motion = float(features.get("motion_energy", 0.0))
    green = float(features.get("green_fraction", 0.0))
    amber = float(features.get("amber_fraction", 0.0))
    red = float(features.get("red_fraction", 0.0))
    brightness = float(features.get("panel_brightness", 0.0))
    if red >= float(thresholds.get("fault_color_fraction", 0.025)):
        return EquipmentState.FAULT, min(0.99, 0.65 + red)
    if green >= float(thresholds.get("run_color_fraction", 0.025)) or motion >= float(
        thresholds.get("motion_energy", 0.045)
    ):
        confidence = min(0.99, 0.65 + max(green, motion))
        return EquipmentState.RUNNING, confidence
    if amber >= float(thresholds.get("idle_color_fraction", 0.025)):
        return EquipmentState.IDLE, min(0.99, 0.65 + amber)
    if brightness >= float(thresholds.get("standby_brightness", 0.12)):
        return EquipmentState.STANDBY, min(0.95, 0.6 + brightness / 2)
    return EquipmentState.OFF, min(0.95, 0.6 + (1 - brightness) / 2)


class TemporalSmoother:
    """N-of-M state hysteresis that delays isolated frame changes."""

    def __init__(self, window: int = 5, votes: int = 3) -> None:
        if window < 1 or not 1 <= votes <= window:
            raise ValueError("votes must be between one and window")
        self.history: deque[EquipmentState] = deque(maxlen=window)
        self.votes = votes
        self.state: EquipmentState | None = None

    def update(self, candidate: EquipmentState) -> EquipmentState:
        self.history.append(candidate)
        counts = {state: self.history.count(state) for state in set(self.history)}
        winner, count = max(counts.items(), key=lambda pair: (pair[1], pair[0].value))
        if self.state is None or (winner == candidate and count >= self.votes):
            self.state = winner
        return self.state


def fit_feature_classifier(labeled_features, seed: int = 42) -> RandomForestClassifier:
    """Fit the optional compact visual state model from clip-level training rows."""
    required = {*FEATURE_COLUMNS, "label_state", "clip_id", "split"}
    if not required.issubset(labeled_features.columns):
        raise ValueError(f"visual training data must contain {sorted(required)}")
    training = labeled_features[labeled_features.split == "train"]
    if training.clip_id.nunique() < 1:
        raise ValueError("at least one training source clip is required")
    labels = training.label_state.astype(str).str.upper()
    if set(labels.unique()) - set(ACTIVITY_STATES):
        raise ValueError("visual state labels must be OFF, STANDBY, IDLE, or RUNNING")
    model = RandomForestClassifier(
        n_estimators=80,
        max_depth=8,
        class_weight="balanced",
        random_state=seed,
        n_jobs=1,
    )
    model.fit(training.loc[:, FEATURE_COLUMNS].fillna(0.0), labels)
    return model


def predict_feature_classifier(model: RandomForestClassifier, features) -> list[dict[str, object]]:
    """Return frame-level state probabilities for temporal smoothing/evaluation."""
    missing = set(FEATURE_COLUMNS) - set(features.columns)
    if missing:
        raise ValueError(f"visual features are missing: {sorted(missing)}")
    matrix = features.loc[:, FEATURE_COLUMNS].fillna(0.0)
    labels = model.predict(matrix)
    probabilities = model.predict_proba(matrix)
    return [
        {"state": str(label), "confidence": float(probability.max())}
        for label, probability in zip(labels, probabilities, strict=True)
    ]
