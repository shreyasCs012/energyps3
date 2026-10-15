"""Allowlisted copilot tool routing with an offline regex fallback."""

import json
import os
import re
from collections.abc import Callable, Mapping
from typing import Any

from contracts.models import CopilotResponse

Tool = Callable[[Mapping[str, Any]], Mapping[str, Any]]
ALLOWED_TOOLS = ("what_if", "get_kpis", "list_anomalies", "forecast")


def _intent(query: str) -> tuple[str, dict[str, Any]]:
    text = query.lower()
    if re.search(r"\b(what[- ]if|simulate|scenario)\b", text):
        equipment = re.search(r"\b(CNC-\d+|C2|CV1|HP1|HVAC|Z[123])\b", query, re.I)
        return "what_if", {
            "query": query,
            **({"equipment": equipment.group(0)} if equipment else {}),
        }
    if re.search(r"\b(anomal(y|ies)|fault|leak|spike)\b", text):
        return "list_anomalies", {"query": query}
    if re.search(r"\b(forecast|predict|upcoming)\b", text):
        horizon = re.search(r"\b(\d+)\s*(?:h|hour)", text)
        return "forecast", {
            "query": query,
            **({"horizon_hours": int(horizon.group(1))} if horizon else {}),
        }
    if re.search(r"\b(kpi|energy|cost|carbon|co2|consumption|savings)\b", text):
        return "get_kpis", {"query": query}
    raise ValueError("Could not map the request to an available copilot tool.")


def _answer(tool: str, result: Mapping[str, Any]) -> str:
    if tool == "get_kpis":
        return "Current KPI results are attached from the configured KPI source."
    if tool == "list_anomalies":
        return "Anomaly results are attached from the configured detection source."
    if tool == "forecast":
        return "Forecast results are attached from the configured forecasting source."
    return "What-if simulation results are attached from the configured twin source."


class Copilot:
    """Route questions to injected, schema-bound tools; no key is needed for regex routing."""

    def __init__(
        self, tools: Mapping[str, Tool], router: Callable[[str], Mapping[str, Any]] | None = None
    ):
        unknown = set(tools) - set(ALLOWED_TOOLS)
        if unknown:
            raise ValueError(f"unsupported copilot tools: {sorted(unknown)}")
        self.tools = dict(tools)
        self.router = router

    def ask(self, query: str) -> CopilotResponse:
        if self.router is not None and os.getenv("LLM_PROVIDER") and os.getenv("LLM_API_KEY"):
            routed = self.router(query)
            tool = routed.get("tool")
            args = routed.get("args", {})
            if tool not in self.tools or not isinstance(args, Mapping):
                raise ValueError("LLM selected an unavailable tool or invalid arguments")
        else:
            tool, args = _intent(query)
        if tool not in self.tools:
            raise ValueError(f"copilot tool is not configured: {tool}")
        result = self.tools[tool](args)
        return CopilotResponse(tool=tool, answer=_answer(tool, result), result=dict(result))


def http_tool_router(query: str) -> Mapping[str, Any]:
    """Use the configured OpenAI-compatible endpoint to select an allowlisted tool."""
    from urllib.request import Request, urlopen

    base_url = os.getenv("LLM_API_BASE_URL", "").rstrip("/")
    model = os.getenv("LLM_MODEL", "")
    provider = os.getenv("LLM_PROVIDER", "")
    api_key = os.getenv("LLM_API_KEY", "")
    if not (base_url and model and provider and api_key):
        raise ValueError("LLM_PROVIDER, LLM_API_KEY, LLM_API_BASE_URL, and LLM_MODEL are required")
    tools = [{"name": name, "description": f"Call the {name} data tool"} for name in ALLOWED_TOOLS]
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": "Return JSON with tool (one allowed tool name) and args object.",
            },
            {"role": "user", "content": json.dumps({"query": query, "tools": tools})},
        ],
        "response_format": {"type": "json_object"},
    }
    request = Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-LLM-Provider": provider,
        },
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        body = json.loads(response.read())
    return json.loads(body["choices"][0]["message"]["content"])
