"""The only preferences that may be stored."""

from __future__ import annotations

import re

from assistflow_customers.errors import SupportError

from assistflow_runtime.redaction import redact_text

PREFERRED_LANGUAGE = "preferred_language"
PREFERRED_CONTACT_CHANNEL = "preferred_contact_channel"
RETENTION_DAYS = 365

PURPOSES = {
    PREFERRED_LANGUAGE: "Use this language when replying to the customer.",
    PREFERRED_CONTACT_CHANNEL: "Use this channel when contacting the customer.",
}

_LANGUAGE_VALUES = {"english": "en", "en": "en", "spanish": "es", "es": "es"}
_CHANNEL_VALUES = {"web": "web", "email": "email", "e-mail": "email"}
_ALLOWED = {
    PREFERRED_LANGUAGE: frozenset(_LANGUAGE_VALUES.values()),
    PREFERRED_CONTACT_CHANNEL: frozenset({"web", "email"}),
}
_LANGUAGE = re.compile(
    r"(?i)\b(?:my\s+)?preferred\s+language\s+is\s+(english|spanish|en|es)\b"
    r"|\blanguage\s*:\s*(english|spanish|en|es)\b"
)
_CHANNEL = re.compile(
    r"(?i)\b(?:my\s+)?preferred\s+contact\s+channel\s+is\s+(web|email|e-mail)\b"
    r"|\bcontact\s+channel\s*:\s*(web|email|e-mail)\b"
)
_SECRET = re.compile(r"(?i)\b(password|passwd|secret)\b")


class PreferenceRejected(SupportError):
    """The value is not one of the two allowed preferences."""

    def __init__(self) -> None:
        super().__init__("preference_rejected", "That preference cannot be stored.", 400)


def preference_statements(text: str) -> list[tuple[str, str]]:
    """Return allowed preferences stated in customer text. Other text is ignored."""
    found: list[tuple[str, str]] = []
    language = _canonical(_LANGUAGE, text, _LANGUAGE_VALUES)
    if language is not None:
        found.append((PREFERRED_LANGUAGE, language))
    channel = _canonical(_CHANNEL, text, _CHANNEL_VALUES)
    if channel is not None:
        found.append((PREFERRED_CONTACT_CHANNEL, channel))
    return found


def validate_preference(key: str, value: str) -> str:
    """Return the stored value, or reject a secret or an unknown key."""
    if key not in _ALLOWED:
        raise PreferenceRejected()
    if _is_secret(value):
        raise PreferenceRejected()
    cleaned = redact_text(value).strip()
    if cleaned != value.strip():
        raise PreferenceRejected()
    canonical = _canonicalize(key, cleaned)
    if canonical is None:
        raise PreferenceRejected()
    return canonical


def _canonicalize(key: str, value: str) -> str | None:
    lowered = value.lower()
    if key == PREFERRED_LANGUAGE:
        return _LANGUAGE_VALUES.get(lowered)
    if key == PREFERRED_CONTACT_CHANNEL:
        return _CHANNEL_VALUES.get(lowered)
    return None


def _canonical(pattern: re.Pattern[str], text: str, mapping: dict[str, str]) -> str | None:
    found = pattern.search(text)
    if found is None:
        return None
    raw = next(group for group in found.groups() if group)
    return mapping[raw.lower()]


def _is_secret(value: str) -> bool:
    if redact_text(value) != value:
        return True
    return _SECRET.search(value) is not None
