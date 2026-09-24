"""Stable hashes for tool arguments.

The hash is `sha256(tool_name + canonical JSON)`. Key order does not change the digest.
"""

import hashlib
import json
from collections.abc import Mapping


def arguments_hash(tool_name: str, arguments: Mapping[str, object]) -> str:
    """Hash a tool name with its canonical arguments."""
    canonical = json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=_encode)
    payload = f"{tool_name}{canonical}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _encode(value: object) -> str:
    return str(value)
