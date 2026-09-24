"""Keyset page cursors. The token is opaque to clients."""

import base64
import binascii
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy.sql import ColumnElement, Select

from assistflow_customers.errors import SupportError


@dataclass(frozen=True)
class PageCursor:
    created_at: datetime
    entity_id: UUID


def encode_cursor(created_at: datetime, entity_id: UUID) -> str:
    raw = f"{created_at.isoformat()}|{entity_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(value: str) -> PageCursor:
    try:
        padded = value + "=" * (-len(value) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        stamp, entity_id = raw.split("|", 1)
        created_at = datetime.fromisoformat(stamp)
    except (ValueError, binascii.Error, UnicodeError) as exc:
        raise SupportError("invalid_cursor", "The page cursor is invalid.", 400) from exc
    if created_at.tzinfo is None:
        raise SupportError("invalid_cursor", "The page cursor is invalid.", 400)
    try:
        parsed_id = UUID(entity_id)
    except ValueError as exc:
        raise SupportError("invalid_cursor", "The page cursor is invalid.", 400) from exc
    return PageCursor(created_at=created_at, entity_id=parsed_id)


@dataclass(frozen=True)
class RecordPage[ItemT]:
    items: list[ItemT]
    next_cursor: str | None


def apply_keyset[RowT](
    statement: Select[tuple[RowT]],
    created_at: object,
    entity_id: object,
    cursor: PageCursor | None,
) -> Select[tuple[RowT]]:
    created = cast(ColumnElement[object], created_at)
    identity = cast(ColumnElement[object], entity_id)
    if cursor is None:
        return statement.order_by(created, identity)
    return statement.where(
        (created > cursor.created_at)
        | ((created == cursor.created_at) & (identity > cursor.entity_id))
    ).order_by(created, identity)


def split_page[ItemT](
    rows: list[ItemT],
    limit: int,
    created_at_of: Callable[[ItemT], datetime],
    id_of: Callable[[ItemT], UUID],
) -> RecordPage[ItemT]:
    if len(rows) <= limit:
        return RecordPage(items=rows, next_cursor=None)
    visible = rows[:limit]
    last = visible[-1]
    return RecordPage(
        items=visible,
        next_cursor=encode_cursor(created_at_of(last), id_of(last)),
    )
