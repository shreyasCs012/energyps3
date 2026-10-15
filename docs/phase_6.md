# Phase 6 — grounded GenAI and copilot

## What was built

- Added the `RecommendationExplanation` and `CopilotResponse` Pydantic contracts and exported JSON Schema and TypeScript definitions.
- Added a deterministic template explainer. It reads recommendation data only and labels its impact as a projected synthetic twin estimate.
- Added an optional provider adapter using `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_API_BASE_URL`, and `LLM_MODEL`. The OpenAI-compatible endpoint receives the structured recommendation JSON. LLM output must satisfy the explanation contract and numeric grounding validator; invalid output is logged and replaced with the deterministic template.
- Added a numeric validator that checks numeric tokens against numeric source values with display-rounding tolerance, plus explicitly permitted derivations.
- Added allowlisted copilot tools for `what_if`, `get_kpis`, `list_anomalies`, and `forecast`. Regex intent routing works without an LLM key; an optional injected router can choose among only configured tools.
- Added an end-of-day Markdown report generator that renders fields present in a results JSON object and labels synthetic results.
- Added `make explain` and `make report` targets.

## How to run

```sh
python -m policies.optimize --input data/generated --output reports/optimizer/recommendations.json
python -m genai.cli --input reports/optimizer/recommendations.json --output reports/optimizer/explanations.json
python -m genai.report reports/analytics/analytics_report.json --output reports/end_of_day.md
```

The template explainer and regex copilot require no network access. To enable the optional default OpenAI-compatible HTTP adapter, configure `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_API_BASE_URL`, and `LLM_MODEL`; credentials are read from the environment. The copilot can be constructed with callbacks implementing the four allowlisted tools. No provider is called unless both provider and key are present.

## Verification

- `python -m pytest -q`: 47 passed (one benign Windows `joblib` physical-core detection warning; it fell back to logical cores).
- `python -m ruff check .`: passed.
- `python -m ruff format --check .`: passed.
- `python -m contracts.export_schema`: passed.
- `git diff --check`: passed.
- Focused tests cover deterministic output, numeric rejection and fallback logging, structured-only explainer input, offline intent routing, tool allowlisting, and report rendering.
- Commit: `1ee2974 feat: add grounded GenAI explanations and copilot`.

## Known gaps

- The LLM adapter uses the common `/chat/completions` JSON interface; provider-specific endpoint differences may need an adapter. Live provider requests were not made during verification.
- Copilot tools are dependency-injected and are not yet wired to the API or dashboard; that integration belongs to Phase 7 and Phase 8.
- The report generator is a general renderer for supplied JSON; the complete cross-policy evaluation results report belongs to Phase 9.
- Numerical validation verifies whether claims are present in structured source data, not whether the source measurements or optimizer projections are physically accurate.
