"""Canonical hashes for idempotent command arguments."""

import hashlib
import json
from collections.abc import Mapping


def canonical_hash(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
