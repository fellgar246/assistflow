"""Boot one hosted turn on the shared loop and tool registry.

The process entry reads a JSON turn from stdin and writes the packaged result.
It does not add a second authorization path.
"""

import json
import sys
from typing import Any

from assistflow_contracts.agent import TurnContext
from sqlalchemy.orm import Session

from assistflow_api.agents import InProcessAgentRunner, build_model_adapter
from assistflow_api.config import Settings, load_settings
from assistflow_api.db import create_db_engine
from assistflow_api.turns import build_turn_gateway
from assistflow_runtime.handler import invoke_turn


def run_payload(session: Session, settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    """Run the turn with the same loop and tenant-scoped tools as the API."""
    turn = TurnContext.model_validate(payload["turn"])
    runner = InProcessAgentRunner(settings, build_model_adapter(settings))
    loop = runner.build_loop(
        build_turn_gateway(
            session,
            tenant_id=turn.tenant_id,
            customer_id=turn.customer_id,
            conversation_id=turn.conversation_id,
            actor_type="customer",
            correlation_id=turn.correlation_id,
            max_tool_calls=settings.max_tool_calls_per_turn,
            max_chunks=settings.max_chunks_per_retrieval,
            score_floor=settings.retrieval_score_floor,
        )
    )
    return invoke_turn(payload, loop)


def main() -> None:
    """Read one turn from stdin and write the packaged result to stdout."""
    settings = load_settings()
    payload = json.load(sys.stdin)
    if not isinstance(payload, dict):
        raise ValueError("The turn payload must be a JSON object.")
    engine = create_db_engine(settings.database_url)
    try:
        with Session(engine) as session:
            body = run_payload(session, settings, payload)
            session.commit()
    finally:
        engine.dispose()
    json.dump(body, sys.stdout)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
