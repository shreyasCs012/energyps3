"""Reject explanation text containing numeric claims absent from its source."""

import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import ValidationError

from contracts.models import RecommendationExplanation

NUMBER = re.compile(r"(?<![\w.])[-+]?\d(?:[\d,]*\d)?(?:\.\d+)?%?(?![\w.])")


def _source_numbers(value: Any) -> list[Decimal]:
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float, Decimal)):
        try:
            return [Decimal(str(value))]
        except InvalidOperation:
            return []
    if isinstance(value, Mapping):
        return [number for item in value.values() for number in _source_numbers(item)]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [number for item in value for number in _source_numbers(item)]
    return []


def _matches(token: str, allowed: list[Decimal]) -> bool:
    percent = token.endswith("%")
    rendered = token[:-1] if percent else token
    try:
        value = Decimal(rendered.replace(",", ""))
    except InvalidOperation:
        return False
    if percent:
        value /= Decimal(100)
    precision = len(rendered.partition(".")[2])
    tolerance = Decimal("0.5") * (Decimal(10) ** -precision)
    return any(abs(value - candidate) <= tolerance for candidate in allowed)


def validate_grounding(
    source: Mapping[str, Any],
    explanation: RecommendationExplanation | Mapping[str, Any],
    *,
    allowed_derived: Sequence[int | float | Decimal] = (),
) -> tuple[bool, list[str]]:
    """Validate every number in explanation text against source values or explicit derivations."""
    try:
        parsed = (
            explanation
            if isinstance(explanation, RecommendationExplanation)
            else RecommendationExplanation.model_validate(explanation)
        )
    except ValidationError as error:
        return False, [f"invalid explanation contract: {error.errors()[0]['msg']}"]
    allowed = _source_numbers(source) + _source_numbers(allowed_derived)
    strings = [
        parsed.summary,
        parsed.rationale,
        *parsed.impact.values(),
        *parsed.constraints,
        *parsed.caveats,
    ]
    unsupported = [
        match.group()
        for text in strings
        for match in NUMBER.finditer(text)
        if not _matches(match.group(), allowed)
    ]
    return not unsupported, unsupported
