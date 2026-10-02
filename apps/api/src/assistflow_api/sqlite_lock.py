"""One lock per SQLite engine so the request and the worker do not share a connection."""

from __future__ import annotations

import threading

from sqlalchemy.engine import Engine

_locks: dict[int, threading.RLock] = {}


def lock_for(engine: Engine) -> threading.RLock | None:
    """Return a reentrant lock for a SQLite engine. Other dialects stay unlocked."""
    if engine.dialect.name != "sqlite":
        return None
    found = _locks.get(id(engine))
    if found is None:
        found = threading.RLock()
        _locks[id(engine)] = found
    return found
