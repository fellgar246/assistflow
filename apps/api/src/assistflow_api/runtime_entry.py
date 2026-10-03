"""Boot one hosted turn on the shared loop.

The process entry reads a JSON turn from stdin and writes the packaged result.
When the hosted agent is enabled, reads leave through the tool gateway.
Otherwise the local gateway is used. This module does not add a second
authorization path.
"""

import json
import sys
from typing import Any

from assistflow_contracts.agent import TurnContext
from sqlalchemy.orm import Session

from assistflow_api.agents import InProcessAgentRunner, build_model_adapter, execution_quota
from assistflow_api.config import Settings, load_settings
from assistflow_api.db import create_db_engine
from assistflow_api.event_queue import InMemoryEventQueue
from assistflow_api.events import build_publisher, make_handler, publish_outbox
from assistflow_api.sqlite_lock import lock_for
from assistflow_runtime.handler import invoke_turn


def run_payload(session: Session, settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    """Run the turn. Hosted reads use the gateway client. Local reads stay in process."""
    turn = TurnContext.model_validate(payload["turn"])
    quota = execution_quota(settings)
    runner = InProcessAgentRunner(settings, build_model_adapter(settings), quota)
    loop = runner.build_loop(_gateway_for(session, settings, turn, quota))
    return invoke_turn(payload, loop)


def _gateway_for(
    session: Session,
    settings: Settings,
    turn: TurnContext,
    quota: object,
) -> Any:
    from assistflow_runtime.quota import ExecutionQuota

    tool_quota = quota if isinstance(quota, ExecutionQuota) else None
    if settings.agentcore_enabled:
        from assistflow_runtime.gateway import build_agentcore_gateway

        return build_agentcore_gateway(
            url=settings.agentcore_gateway_url,
            token=settings.agentcore_gateway_token,
            secret=settings.agentcore_actor_context_secret,
            tool_quota=tool_quota,
        )
    from assistflow_api.turns import build_turn_gateway

    return build_turn_gateway(
        session,
        max_tool_calls=settings.max_tool_calls_per_turn,
        max_chunks=settings.max_chunks_per_retrieval,
        score_floor=settings.retrieval_score_floor,
        settings=settings,
        tool_quota=tool_quota,
    )


def main() -> None:
    """Read one turn from stdin and write the packaged result to stdout."""
    settings = load_settings()
    payload = json.load(sys.stdin)
    if not isinstance(payload, dict):
        raise ValueError("The turn payload must be a JSON object.")
    engine = create_db_engine(settings.database_url)
    lock_for(engine)
    events = InMemoryEventQueue(make_handler(engine, settings))
    publisher = build_publisher(settings, events)
    try:
        with Session(engine) as session:
            body = run_payload(session, settings, payload)
            session.commit()
            publish_outbox(session, publisher)
        json.dump(body, sys.stdout)
        sys.stdout.write("\n")
        sys.stdout.flush()
        if publisher is events:
            events.drain()
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
