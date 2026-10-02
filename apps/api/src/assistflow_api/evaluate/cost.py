"""Token-price table. A missing model id yields a null cost."""

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TokenPrice(BaseModel):
    """Price for one million tokens. The operator supplies the numbers."""

    model_config = ConfigDict(extra="forbid")

    input_per_million: float = Field(ge=0)
    output_per_million: float = Field(ge=0)


def load_prices(path: Path) -> dict[str, TokenPrice]:
    """Read a price table. An empty object prices nothing."""
    if not path.is_file():
        return {}
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("The price table must be a JSON object.")
    prices: dict[str, TokenPrice] = {}
    for model_id, raw in loaded.items():
        if not isinstance(model_id, str) or not isinstance(raw, dict):
            raise ValueError("Each price entry needs a model id and an object.")
        prices[model_id] = TokenPrice.model_validate(raw)
    return prices


def estimate_cost(
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    prices: dict[str, TokenPrice],
) -> float | None:
    """Estimate session cost from token counts. Unknown models stay null."""
    price = prices.get(model_id)
    if price is None:
        return None
    total = (
        input_tokens * price.input_per_million + output_tokens * price.output_per_million
    ) / 1_000_000
    return round(total, 6)


def price_document(prices: dict[str, TokenPrice]) -> dict[str, Any]:
    """Serialize a table the same way it was loaded."""
    return {
        model_id: {
            "input_per_million": price.input_per_million,
            "output_per_million": price.output_per_million,
        }
        for model_id, price in prices.items()
    }
