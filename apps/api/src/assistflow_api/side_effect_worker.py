"""Hosted consumer. It calls the same handlers as the in-process queue."""

from __future__ import annotations

import json
from typing import Any

import structlog
from assistflow_conversations.outbox import event_from_body
from assistflow_conversations.side_effects import apply_side_effects
from sqlalchemy.orm import Session

from assistflow_api.config import load_settings
from assistflow_api.db import create_db_engine

logger = structlog.get_logger(__name__)

__all__ = ["apply_side_effects", "lambda_handler"]


def lambda_handler(event: dict[str, Any], _context: object) -> dict[str, int]:
    """Deliver each SQS record. A failure is raised so the message stays visible for retry."""
    settings = load_settings()
    engine = create_db_engine(settings.database_url)
    records = event.get("Records", [])
    if not isinstance(records, list):
        raise ValueError("The consumer event did not include records.")
    processed = 0
    try:
        for record in records:
            if not isinstance(record, dict):
                raise ValueError("A consumer record was not an object.")
            raw_body = record.get("body", "")
            if not isinstance(raw_body, str):
                raise ValueError("A consumer record body was not text.")
            parsed = json.loads(raw_body)
            if not isinstance(parsed, dict):
                raise ValueError("A consumer record body was not an object.")
            domain = event_from_body(parsed)
            try:
                with Session(engine) as session:
                    apply_side_effects(session, domain, sample_rate=settings.eval_sample_rate)
            except Exception:
                logger.exception(
                    "side_effect_consumer_failed",
                    event_id=str(domain.event_id),
                    event_name=domain.name,
                )
                raise
            processed += 1
    finally:
        engine.dispose()
    return {"processed": processed}
