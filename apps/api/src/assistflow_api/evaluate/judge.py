"""Qualitative judge gate. The local suite does not construct one."""

from typing import Protocol

_constructed = 0


class QualitativeJudge(Protocol):
    """Optional scores. They never decide the process exit code."""

    def scores(self) -> dict[str, str]:
        """Return qualitative metric values."""


class UnconfiguredJudge:
    """Placeholder constructed only when the judge flag is on and no judge is injected."""

    def __init__(self) -> None:
        global _constructed
        _constructed += 1

    def scores(self) -> dict[str, str]:
        raise RuntimeError("A qualitative judge is not configured.")


def judges_constructed() -> int:
    """How many unconfigured judges this process has constructed."""
    return _constructed


def reset_judge_count() -> None:
    """Test helper."""
    global _constructed
    _constructed = 0


def build_judge() -> UnconfiguredJudge:
    """Construct a judge. The local command does not call this."""
    return UnconfiguredJudge()
