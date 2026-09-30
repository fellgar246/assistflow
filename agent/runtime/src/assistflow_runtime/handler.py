"""Hosted turn entry. Tool authorization stays on the shared loop."""

from typing import Any

from assistflow_contracts.agent import AgentResult, TurnContext

from assistflow_runtime.facts import domain_facts
from assistflow_runtime.loop import AgentLoop


def package_result(result: AgentResult) -> dict[str, Any]:
    """Serialize one turn plus the domain facts a smoke check compares."""
    return {
        "result": result.model_dump(mode="json"),
        "domain": domain_facts(result).model_dump(mode="json"),
    }


def invoke_turn(payload: dict[str, Any], loop: AgentLoop) -> dict[str, Any]:
    """Run one turn through the shared loop.

    The payload carries the turn. This function does not authorize tools itself.
    """
    turn = TurnContext.model_validate(payload["turn"])
    return package_result(loop.run(turn))
