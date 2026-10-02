"""Load the golden scenario file."""

import json
from collections import Counter
from pathlib import Path

from assistflow_api.config import repo_root
from assistflow_api.evaluate.schema import MINIMUM_COUNTS, MINIMUM_TOTAL, Scenario


def scenario_path() -> Path:
    """Product path of the golden scenario file."""
    return repo_root() / "agent" / "evaluations" / "scenarios.json"


def price_path() -> Path:
    """Operator-edited token prices. Missing entries do not invent a vendor rate."""
    return repo_root() / "agent" / "evaluations" / "prices.json"


def load_scenarios(path: Path | None = None) -> list[Scenario]:
    """Read and validate scenarios. Duplicate ids are an error."""
    source = scenario_path() if path is None else path
    loaded = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(loaded, list):
        raise ValueError("The scenario file must be a JSON list.")
    scenarios = [Scenario.model_validate(item) for item in loaded]
    ids = [item.id for item in scenarios]
    if len(ids) != len(set(ids)):
        raise ValueError("Scenario ids must be unique.")
    return scenarios


def require_minimums(scenarios: list[Scenario]) -> None:
    """Refuse a corpus that is below the category floors or the overall floor."""
    counts: Counter[str] = Counter(item.category.value for item in scenarios)
    short = [
        f"{category.value} has {counts[category.value]} (minimum {minimum})"
        for category, minimum in MINIMUM_COUNTS.items()
        if counts[category.value] < minimum
    ]
    if len(scenarios) < MINIMUM_TOTAL:
        short.append(f"total has {len(scenarios)} (minimum {MINIMUM_TOTAL})")
    if short:
        raise ValueError("Scenario corpus is short: " + "; ".join(short))
