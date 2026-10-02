"""Test hook that fails one named tool a single time.

The failure is a safe tool error. It does not include a stack trace.
"""

from threading import Lock

_pending: list[str] = []
_lock = Lock()


def fail_tool_once(name: str) -> None:
    """The next call to `name` fails and later calls run normally."""
    with _lock:
        _pending.append(name)


def take_fault(name: str) -> bool:
    """Consume one pending failure for `name`."""
    with _lock:
        if name not in _pending:
            return False
        _pending.remove(name)
        return True


def clear_faults() -> None:
    """Drop pending failures. Tests call this so later cases stay clean."""
    with _lock:
        _pending.clear()
