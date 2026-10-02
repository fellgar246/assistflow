"""Comparable evaluation report. Metric names stay in a fixed order."""

import json
from pathlib import Path
from typing import Any

from assistflow_api.evaluate.schema import METRIC_NAMES, QUALITATIVE_METRICS, SAFETY_METRICS


def qualitative_scores(judge_enabled: bool, judged: dict[str, str] | None) -> dict[str, str]:
    """Record qualitative keys. The judge stays off unless a caller supplies scores."""
    if not judge_enabled or judged is None:
        return {name: "not_run" for name in QUALITATIVE_METRICS}
    return {name: judged.get(name, "not_run") for name in QUALITATIVE_METRICS}


def build_report(
    *,
    prompt_id: str,
    prompt_version: str,
    provider: str,
    rows: list[dict[str, Any]],
    qualitative: dict[str, str],
) -> dict[str, Any]:
    """Assemble one report. Scenario ids are sorted and metric names are fixed."""
    ordered = sorted(rows, key=lambda item: str(item["id"]))
    totals = {name: 0 for name in METRIC_NAMES}
    passed = {name: 0 for name in METRIC_NAMES}
    for row in ordered:
        scores = row["scores"]
        if not isinstance(scores, dict):
            raise ValueError("Each scenario row needs scores.")
        for name in METRIC_NAMES:
            totals[name] += 1
            if scores.get(name) is True:
                passed[name] += 1
    safety_passed = all(passed[name] == totals[name] for name in SAFETY_METRICS)
    return {
        "prompt_id": prompt_id,
        "prompt_version": prompt_version,
        "provider": provider,
        "scenario_count": len(ordered),
        "metrics": {name: {"passed": passed[name], "total": totals[name]} for name in METRIC_NAMES},
        "qualitative": {name: qualitative[name] for name in QUALITATIVE_METRICS},
        "safety_passed": safety_passed,
        "scenarios": ordered,
    }


def safety_failed(report: dict[str, Any]) -> bool:
    """True when a safety metric missed at least one scenario."""
    return report.get("safety_passed") is not True


def write_report(report: dict[str, Any], json_path: Path, markdown_path: Path) -> None:
    """Write the machine-readable report and a short generated summary."""
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")


def render_markdown(report: dict[str, Any]) -> str:
    """Summarize metric totals. This text is generated from the report."""
    prompt = f"{report['prompt_id']} version {report['prompt_version']}"
    safety = "passed" if report["safety_passed"] else "failed"
    lines = [
        "# Evaluation summary",
        "",
        f"Prompt {prompt}. Provider {report['provider']}. {report['scenario_count']} scenarios.",
        "",
        f"Safety: {safety}.",
        "",
        "| Metric | Passed | Total |",
        "|---|---:|---:|",
    ]
    metrics = report["metrics"]
    if isinstance(metrics, dict):
        for name in METRIC_NAMES:
            item = metrics[name]
            lines.append(f"| `{name}` | {item['passed']} | {item['total']} |")
    lines.extend(["", "Qualitative scores:", ""])
    qualitative = report["qualitative"]
    if isinstance(qualitative, dict):
        for name in QUALITATIVE_METRICS:
            lines.append(f"- `{name}`: {qualitative[name]}")
    lines.append("")
    return "\n".join(lines)
