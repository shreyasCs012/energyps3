"""Generate an end-of-day Markdown report from a results JSON object."""

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def _render(value: Any, depth: int = 0) -> list[str]:
    indent = "  " * depth
    if isinstance(value, bool):
        return [indent + ("Yes" if value else "No")]
    if value is None:
        return [indent + "Not available"]
    if isinstance(value, Mapping):
        lines = []
        for key, item in value.items():
            if isinstance(item, (Mapping, list)):
                lines.append(f"{indent}- **{key}:**")
                lines.extend(_render(item, depth + 1))
            else:
                rendered = _render(item, 0)[0]
                lines.append(f"{indent}- **{key}:** {rendered}")
        return lines or [indent + "None"]
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, (Mapping, list)):
                lines.extend(_render(item, depth))
            else:
                lines.append(f"{indent}- {_render(item, 0)[0]}")
        return lines or [indent + "None"]
    return [indent + str(value)]


def generate_report(results: Mapping[str, Any]) -> str:
    """Render supplied results without filling missing metrics with assumed values."""
    lines = ["# End-of-day energy report", ""]
    if results.get("synthetic") is True:
        lines.extend(["**SYNTHETIC DATA — simulation-based projections**", ""])
    for key, value in results.items():
        if key == "synthetic":
            continue
        title = str(key).replace("_", " ").strip().title()
        lines.extend([f"## {title}", "", *_render(value), ""])
    if len(lines) == 2:
        lines.append("No result fields were provided.")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Path to a JSON results object")
    parser.add_argument("--output", default="reports/end_of_day.md")
    args = parser.parse_args()
    results = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if not isinstance(results, Mapping):
        raise ValueError("results JSON must contain an object")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(generate_report(results), encoding="utf-8")
    print(f"Wrote end-of-day report to {output}")


if __name__ == "__main__":
    main()
