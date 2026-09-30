"""Embedding port. The deterministic provider never calls a hosted API."""

import hashlib
import math
import re
from typing import Protocol

DIMENSIONS = 256
_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    {
        "a",
        "an",
        "and",
        "the",
        "to",
        "of",
        "for",
        "in",
        "on",
        "is",
        "it",
        "or",
        "do",
        "i",
        "my",
        "how",
        "what",
        "does",
        "can",
        "with",
    }
)


class EmbeddingProvider(Protocol):
    """Map text to a unit vector. Implementations must be side-effect free."""

    def embed(self, text: str) -> list[float]:
        """Return one vector for the given text."""


class DeterministicEmbedding:
    """Hash content words into a fixed vector so tests stay offline."""

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * DIMENSIONS
        for token in _TOKEN.findall(text.lower()):
            if token in _STOP or len(token) < 3:
                continue
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:2], "big") % DIMENSIONS
            sign = 1.0 if digest[1] % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]


def cosine(left: list[float], right: list[float]) -> float:
    """Cosine similarity of two equal-length vectors. Missing overlap scores zero."""
    if len(left) != len(right) or not left:
        return 0.0
    return float(sum(a * b for a, b in zip(left, right, strict=True)))
