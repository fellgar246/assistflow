"""Per-turn execution caps. Callers pass values from configuration."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TurnLimits:
    max_agent_steps: int
    max_tool_calls_per_turn: int
    max_model_calls_per_turn: int
    max_output_tokens: int = 800
    max_input_tokens: int = 6000
