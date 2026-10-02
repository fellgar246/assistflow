"""Run the local evaluation suite.

Hosted evaluations and the qualitative judge stay unconstructed unless their flags are on.
"""

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from assistflow_api.config import load_settings, repo_root
from assistflow_api.evaluate.cost import load_prices
from assistflow_api.evaluate.load import load_scenarios, price_path, require_minimums
from assistflow_api.evaluate.report import safety_failed, write_report
from assistflow_api.evaluate.runner import run_suite
from assistflow_api.evaluate.sampling import list_sampling_markers


def main(argv: list[str] | None = None) -> int:
    """Score the golden file and write a report. Safety misses exit non-zero."""
    parser = argparse.ArgumentParser(description="Run the local evaluation suite.")
    parser.add_argument("--prompt-id", default="local-support")
    parser.add_argument("--prompt-version", default="1")
    parser.add_argument(
        "--report",
        type=Path,
        default=repo_root() / "test-results" / "evaluations" / "report.json",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=repo_root() / "test-results" / "evaluations" / "summary.md",
    )
    parser.add_argument("--prices", type=Path, default=None)
    parser.add_argument("--hosted", action="store_true")
    parser.add_argument("--judge", action="store_true")
    parser.add_argument("--list-samples", action="store_true")
    args = parser.parse_args(argv)
    if args.list_samples:
        return _print_samples()
    scenarios = load_scenarios()
    require_minimums(scenarios)
    prices = load_prices(args.prices if args.prices is not None else price_path())
    report = run_suite(
        scenarios,
        prompt_id=args.prompt_id,
        prompt_version=args.prompt_version,
        prices=prices,
        hosted_enabled=args.hosted or _flag("HOSTED_EVALUATIONS"),
        judge_enabled=args.judge or _flag("EVAL_JUDGE_ENABLED"),
    )
    write_report(report, args.report, args.summary)
    print(
        f"scenarios={report['scenario_count']} safety_passed={report['safety_passed']} "
        f"report={args.report}"
    )
    if safety_failed(report):
        _print_safety_misses(report)
        return 1
    return 0


def _print_samples() -> int:
    settings = load_settings()
    engine = create_engine(settings.database_url)
    try:
        with Session(engine) as session:
            markers = list_sampling_markers(session)
    finally:
        engine.dispose()
    for marker in markers:
        print(
            f"{marker.id} tenant={marker.tenant_id} "
            f"conversation={marker.conversation_id} event={marker.event_id}"
        )
    print(f"samples={len(markers)}")
    return 0


def _print_safety_misses(report: dict[str, object]) -> None:
    rows = report.get("scenarios")
    if not isinstance(rows, list):
        return
    for row in rows:
        if not isinstance(row, dict):
            continue
        scores = row.get("scores")
        if not isinstance(scores, dict):
            continue
        missed = [
            name
            for name in (
                "forbidden_tool_not_called",
                "approval_required_when_expected",
                "no_cross_tenant_access",
                "max_steps_respected",
            )
            if scores.get(name) is not True
        ]
        if missed:
            print(f"{row.get('id')}: {', '.join(missed)}", file=sys.stderr)


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


if __name__ == "__main__":
    raise SystemExit(main())
