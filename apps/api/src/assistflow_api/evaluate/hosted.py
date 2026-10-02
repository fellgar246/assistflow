"""Optional hosted evaluation submitter.

The client object is constructed only when hosted evaluations are enabled.
"""

from typing import Protocol

_constructed = 0


class HostedEvaluationClient(Protocol):
    """Submit the local scenario ids. Implementations perform the remote call."""

    def submit(self, scenario_ids: list[str]) -> None:
        """Send ids. The ids must match the local scenario file."""


class AgentCoreEvaluationSubmitter:
    """Hosted evaluations client. Constructing it is the opt-in step."""

    def __init__(self) -> None:
        global _constructed
        _constructed += 1

    def submit(self, scenario_ids: list[str]) -> None:
        """Refuse to call a hosted API from the local suite."""
        if not scenario_ids:
            raise ValueError("No scenario ids to submit.")
        raise RuntimeError("Hosted evaluations are not configured.")


def hosted_clients_constructed() -> int:
    """How many hosted clients this process has constructed."""
    return _constructed


def reset_hosted_client_count() -> None:
    """Test helper. Production runs do not reset this."""
    global _constructed
    _constructed = 0


def build_hosted_client() -> AgentCoreEvaluationSubmitter:
    """Construct the hosted client. Callers skip this while the flag is off."""
    return AgentCoreEvaluationSubmitter()


def submit_scenarios(client: HostedEvaluationClient, scenario_ids: list[str]) -> None:
    """Send the same ids the local file uses, in file order."""
    client.submit(list(scenario_ids))
