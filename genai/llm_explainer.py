"""Optional OpenAI-compatible JSON endpoint with deterministic safe fallback."""

import json
import logging
import os
from collections.abc import Callable, Mapping
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from contracts.models import RecommendationExplanation
from genai.grounding_validator import validate_grounding
from genai.template_explainer import derived_values, explain_template

logger = logging.getLogger(__name__)
Completion = Callable[[str, Mapping[str, Any]], str | Mapping[str, Any]]


def _http_completion(provider: str, api_key: str, source: Mapping[str, Any]) -> str:
    base_url = os.getenv("LLM_API_BASE_URL", "").rstrip("/")
    model = os.getenv("LLM_MODEL", "")
    if not base_url or not model:
        raise ValueError("LLM_API_BASE_URL and LLM_MODEL are required for the configured provider")
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Return JSON with summary, rationale, impact, constraints, caveats. "
                    "Use only numeric values in the supplied JSON; do not invent or derive numbers."
                ),
            },
            {"role": "user", "content": json.dumps(source, sort_keys=True)},
        ],
        "response_format": {"type": "json_object"},
    }
    request = Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-LLM-Provider": provider,
        },
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        response_json = json.loads(response.read())
    return response_json["choices"][0]["message"]["content"]


def explain(
    recommendation_json: Mapping[str, Any],
    *,
    completion: Completion | None = None,
) -> RecommendationExplanation:
    """Use optional completion only after contract and grounding checks."""
    provider = os.getenv("LLM_PROVIDER", "").strip()
    api_key = os.getenv("LLM_API_KEY", "").strip()
    if not provider or not api_key:
        return explain_template(recommendation_json)
    try:
        request_completion = completion or (
            lambda configured_provider, source: _http_completion(
                configured_provider, api_key, source
            )
        )
        raw = request_completion(provider, recommendation_json)
        parsed = RecommendationExplanation.model_validate(
            json.loads(raw) if isinstance(raw, str) else raw
        )
        valid, unsupported = validate_grounding(
            recommendation_json, parsed, allowed_derived=derived_values(recommendation_json)
        )
        if not valid:
            logger.warning(
                "Rejected LLM explanation with unsupported numeric tokens: %s", unsupported
            )
            return explain_template(recommendation_json)
        return parsed
    except (ValueError, KeyError, TypeError, URLError, json.JSONDecodeError) as error:
        logger.warning("LLM explanation failed; using deterministic template: %s", error)
        return explain_template(recommendation_json)
