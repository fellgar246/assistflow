"""Replace bearer tokens, access-key ids, and card numbers before they are stored."""

from __future__ import annotations

import re

REDACTED = "[redacted]"

_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-._~+/=]{8,}")
_AWS_ACCESS_KEY = re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])")
_PAN = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_UUID = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)


def redact_text(text: str) -> str:
    """Remove secret-shaped substrings. Other text is unchanged."""
    cleaned = _BEARER.sub(REDACTED, text)
    cleaned = _AWS_ACCESS_KEY.sub(REDACTED, cleaned)
    spans = [(item.start(), item.end()) for item in _UUID.finditer(cleaned)]

    def replace(match: re.Match[str]) -> str:
        if any(start < match.end() and match.start() < end for start, end in spans):
            return match.group(0)
        return _replace_pan(match)

    return _PAN.sub(replace, cleaned)


def redact_data(value: object) -> object:
    """Redact strings inside nested documents. Numbers and booleans stay as they are."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_data(item) for item in value]
    if isinstance(value, dict):
        return {str(key): redact_data(item) for key, item in value.items()}
    return value


def _replace_pan(match: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", match.group(0))
    if 13 <= len(digits) <= 19 and _luhn(digits):
        return REDACTED
    return match.group(0)


def _luhn(number: str) -> bool:
    checksum = 0
    for index, character in enumerate(reversed(number)):
        digit = int(character)
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0
