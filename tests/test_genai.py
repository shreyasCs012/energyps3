import logging

import pytest

from genai.copilot import Copilot
from genai.grounding_validator import validate_grounding
from genai.llm_explainer import explain
from genai.report import generate_report
from genai.template_explainer import explain_template


@pytest.fixture
def recommendation():
    return {
        "id": "rec-1",
        "equipment": "CNC-01",
        "action": "STANDBY",
        "projected": {"energy_kwh": 1.256, "cost_inr": 9.42, "co2_kg": 0.89, "peak_kw": 0.2},
        "confidence": 0.92,
        "constraints": [{"rule": "break_even", "passed": True, "detail": "gap is sufficient"}],
    }


def test_template_explainer_is_deterministic_and_grounded(recommendation):
    explanation = explain_template(recommendation)
    assert explanation == explain_template(recommendation)
    valid, unsupported = validate_grounding(recommendation, explanation, allowed_derived=[92])
    assert valid, unsupported
    assert "1.26 kWh" in explanation.summary
    assert "92%" in explanation.rationale


def test_grounding_validator_rejects_fabricated_numbers(recommendation):
    fabricated = explain_template(recommendation).model_dump()
    fabricated["summary"] = "This action saves 999 kWh."
    valid, unsupported = validate_grounding(recommendation, fabricated)
    assert not valid
    assert "999" in unsupported


def test_llm_explainer_falls_back_when_grounding_fails(recommendation, monkeypatch, caplog):
    monkeypatch.setenv("LLM_PROVIDER", "test-provider")
    monkeypatch.setenv("LLM_API_KEY", "test-key")

    def completion(provider, source):
        assert provider == "test-provider"
        assert source == recommendation
        return {**explain_template(recommendation).model_dump(), "summary": "Saves 500 kWh."}

    with caplog.at_level(logging.WARNING):
        result = explain(recommendation, completion=completion)
    assert result == explain_template(recommendation)
    assert "unsupported numeric tokens" in caplog.text


def test_llm_payload_is_only_structured_recommendation(recommendation, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "configured")
    monkeypatch.setenv("LLM_API_KEY", "secret")
    seen = {}

    def completion(provider, source):
        seen.update(provider=provider, source=source)
        return explain_template(recommendation).model_dump()

    explain(recommendation, completion=completion)
    assert seen == {"provider": "configured", "source": recommendation}


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Show energy KPIs", "get_kpis"),
        ("List anomalies", "list_anomalies"),
        ("Forecast the next 4 hours", "forecast"),
        ("What if CNC-01 goes to standby?", "what_if"),
    ],
)
def test_copilot_routes_offline_intents(query, expected):
    tools = {
        name: lambda args, selected=name: {"called": selected, "args": dict(args)}
        for name in ("get_kpis", "list_anomalies", "forecast", "what_if")
    }
    response = Copilot(tools).ask(query)
    assert response.tool == expected
    assert response.result["called"] == expected


def test_copilot_rejects_unknown_llm_tool(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "provider")
    monkeypatch.setenv("LLM_API_KEY", "key")
    copilot = Copilot({"get_kpis": lambda _: {}}, router=lambda _: {"tool": "shell", "args": {}})
    with pytest.raises(ValueError, match="unavailable tool"):
        copilot.ask("show KPIs")


def test_report_uses_results_fields_and_marks_synthetic():
    report = generate_report({"synthetic": True, "scenario": "S2", "kpis": {"energy_kwh": 12.5}})
    assert "SYNTHETIC DATA" in report
    assert "12.5" in report
    assert "S2" in report
    assert "999" not in report
