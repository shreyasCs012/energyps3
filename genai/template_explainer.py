"""Deterministic recommendation explanations grounded in optimizer output."""

from collections.abc import Mapping
from typing import Any

from contracts.models import RecommendationExplanation


def _recommendation(value: Mapping[str, Any]) -> dict[str, Any]:
    if "recommendation" in value and isinstance(value["recommendation"], Mapping):
        return dict(value["recommendation"])
    return dict(value)


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def explain_template(recommendation_json: Mapping[str, Any]) -> RecommendationExplanation:
    """Produce concise deterministic text; all reported metrics come from the input."""
    rec = _recommendation(recommendation_json)
    equipment = str(rec.get("equipment", "equipment"))
    action = str(rec.get("action", "action"))
    projected = rec.get("projected", {})
    projected = projected if isinstance(projected, Mapping) else {}
    confidence = _number(rec.get("confidence", 0))
    energy = _number(projected.get("energy_kwh", 0))
    cost = _number(projected.get("cost_inr", 0))
    co2 = _number(projected.get("co2_kg", 0))
    peak = _number(projected.get("peak_kw", 0))
    constraints_raw = rec.get("constraints", [])
    constraints: list[str] = []
    if isinstance(constraints_raw, list):
        for item in constraints_raw:
            if isinstance(item, Mapping):
                state = "passed" if item.get("passed") else "failed"
                constraints.append(
                    f"{item.get('rule', 'constraint')}: {state}; {item.get('detail', '')}".strip()
                )
    if not constraints:
        constraints.append("No constraint checks were included in the recommendation.")
    caveats = [
        "Projected deltas are estimates from the synthetic digital twin, not measured savings."
    ]
    if not 0 <= confidence <= 1:
        caveats.append("The supplied confidence value is outside its expected range.")
    explanation = RecommendationExplanation(
        summary=f"{action} for {equipment} has a projected energy delta of {energy:.2f} kWh.",
        rationale=(
            f"The optimizer selected {action} for {equipment}; its confidence is "
            f"{confidence * 100:.0f}%. Review the listed checks before applying it."
        ),
        impact={
            "energy": f"{energy:.2f} kWh projected delta",
            "cost": f"{cost:.2f} INR projected delta",
            "carbon": f"{co2:.2f} kg CO2 projected delta",
            "peak": f"{peak:.2f} kW projected delta",
        },
        constraints=constraints,
        caveats=caveats,
    )
    return explanation


def derived_values(recommendation_json: Mapping[str, Any]) -> list[float]:
    """Return the only derived display value currently allowed: confidence as percent."""
    rec = _recommendation(recommendation_json)
    return [_number(rec.get("confidence", 0)) * 100]
