"""Explain recommendations from an optimizer plan JSON file."""

import argparse
import json
from pathlib import Path

from genai.llm_explainer import explain


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="reports/optimizer/recommendations.json")
    parser.add_argument("--output", default="reports/optimizer/explanations.json")
    args = parser.parse_args()
    plan = json.loads(Path(args.input).read_text(encoding="utf-8"))
    recommendations = plan.get("recommendations")
    if not isinstance(recommendations, list):
        raise ValueError("input JSON must contain a recommendations array")
    explanations = [explain(item).model_dump(mode="json") for item in recommendations]
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(explanations, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(explanations)} recommendation explanations to {output}")


if __name__ == "__main__":
    main()
