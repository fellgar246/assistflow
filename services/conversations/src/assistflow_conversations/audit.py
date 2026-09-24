"""Redacted audit payloads. Secrets are dropped. Long fields are truncated."""

from collections.abc import Mapping

MAX_AUDIT_FIELD_CHARS = 256

_SECRET_MARKERS = ("token", "password", "secret", "authorization", "api_key")


def audit_payload(fields: Mapping[str, object]) -> dict[str, object]:
    """Keep identifying fields only. Mark the payload when a value was shortened."""
    cleaned: dict[str, object] = {}
    truncated = False
    for key, value in fields.items():
        lowered = key.lower()
        if any(marker in lowered for marker in _SECRET_MARKERS):
            continue
        if isinstance(value, str) and len(value) > MAX_AUDIT_FIELD_CHARS:
            cleaned[key] = value[:MAX_AUDIT_FIELD_CHARS]
            truncated = True
        else:
            cleaned[key] = value
    if truncated:
        cleaned["truncated"] = True
    return cleaned
