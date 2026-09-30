"""Execution profile and process settings.

Missing environment variables resolve to the local profile, with AWS left off.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}

DEFAULT_DATABASE_URL = "postgresql+psycopg://assistflow:assistflow@localhost:54329/assistflow"


class ExecutionMode(StrEnum):
    LOCAL = "local"
    AWS_DEMO = "aws-demo"
    SHOWCASE = "showcase"


class RagProvider(StrEnum):
    LOCAL = "local"
    MANAGED = "managed"


class ModelProvider(StrEnum):
    MOCK = "mock"
    BEDROCK = "bedrock"


class ProfileDefaults(BaseModel):
    model_config = ConfigDict(frozen=True)

    aws_enabled: bool
    agentcore_enabled: bool
    bedrock_enabled: bool
    rag_provider: RagProvider
    ai_enabled: bool
    long_term_memory_enabled: bool
    managed_rag_enabled: bool


_PROFILES: dict[ExecutionMode, ProfileDefaults] = {
    ExecutionMode.LOCAL: ProfileDefaults(
        aws_enabled=False,
        agentcore_enabled=False,
        bedrock_enabled=False,
        rag_provider=RagProvider.LOCAL,
        ai_enabled=True,
        long_term_memory_enabled=False,
        managed_rag_enabled=False,
    ),
    ExecutionMode.AWS_DEMO: ProfileDefaults(
        aws_enabled=True,
        agentcore_enabled=True,
        bedrock_enabled=True,
        rag_provider=RagProvider.LOCAL,
        ai_enabled=True,
        long_term_memory_enabled=False,
        managed_rag_enabled=False,
    ),
    ExecutionMode.SHOWCASE: ProfileDefaults(
        aws_enabled=True,
        agentcore_enabled=True,
        bedrock_enabled=True,
        rag_provider=RagProvider.LOCAL,
        ai_enabled=True,
        long_term_memory_enabled=True,
        managed_rag_enabled=False,
    ),
}


class Settings(BaseModel):
    """Resolved process configuration."""

    model_config = ConfigDict(frozen=True)

    execution_mode: ExecutionMode
    aws_enabled: bool
    agentcore_enabled: bool
    bedrock_enabled: bool
    rag_provider: RagProvider
    ai_enabled: bool
    long_term_memory_enabled: bool
    managed_rag_enabled: bool
    local_only_mode: bool
    database_url: str
    model_provider: ModelProvider = ModelProvider.MOCK
    bedrock_model_id: str = "anthropic.claude-3-5-haiku-20241022-v1:0"
    aws_region: str = "us-east-1"
    trace_debug: bool = False
    max_agent_steps: int = 8
    max_tool_calls_per_turn: int = 5
    max_model_calls_per_turn: int = 4
    max_retrievals_per_turn: int = 2
    max_chunks_per_retrieval: int = 4
    retrieval_score_floor: float = 0.28
    max_session_minutes: int = 20
    max_output_tokens: int = 800
    max_sessions_per_day: int = 25
    max_tool_calls_per_session: int = 15
    max_bedrock_input_tokens_per_call: int = 6000
    max_bedrock_output_tokens_per_call: int = 800
    max_memory_events_per_session: int = 30


def repo_root() -> Path:
    """Product root that contains the Compose file."""
    return Path(__file__).resolve().parents[4]


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Load settings from the environment.

    An explicit mapping is used as-is so tests stay isolated from the developer
    environment. When omitted, a local dotenv file fills only unset variables.
    """
    if environ is None:
        values = _read_env_file(repo_root() / ".env")
        values.update(os.environ)
    else:
        values = dict(environ)

    mode = _execution_mode(values.get("EXECUTION_MODE"))
    defaults = _PROFILES[mode]
    local_only = _optional_bool(values, "LOCAL_ONLY_MODE", False)
    aws_enabled = _optional_bool(values, "AWS_ENABLED", defaults.aws_enabled)
    agentcore_enabled = _optional_bool(values, "AGENTCORE_ENABLED", defaults.agentcore_enabled)
    bedrock_enabled = _optional_bool(values, "BEDROCK_ENABLED", defaults.bedrock_enabled)
    managed_rag_enabled = _optional_bool(
        values, "MANAGED_RAG_ENABLED", defaults.managed_rag_enabled
    )
    long_term_memory_enabled = _optional_bool(
        values, "LONG_TERM_MEMORY_ENABLED", defaults.long_term_memory_enabled
    )
    rag_provider = _rag_provider(values.get("RAG_PROVIDER"), defaults.rag_provider)
    ai_enabled = _optional_bool(values, "AI_ENABLED", defaults.ai_enabled)

    if local_only:
        aws_enabled = False
        agentcore_enabled = False
        bedrock_enabled = False
        managed_rag_enabled = False
        long_term_memory_enabled = False
        if rag_provider is RagProvider.MANAGED:
            rag_provider = RagProvider.LOCAL

    database_url = values.get("DATABASE_URL", "").strip() or DEFAULT_DATABASE_URL
    model_provider = _model_provider(values.get("MODEL_PROVIDER"))
    if model_provider is ModelProvider.BEDROCK and (local_only or not bedrock_enabled):
        model_provider = ModelProvider.MOCK
    bedrock_model_id = values.get("BEDROCK_MODEL_ID", "").strip() or (
        "anthropic.claude-3-5-haiku-20241022-v1:0"
    )
    aws_region = values.get("AWS_REGION", "").strip() or "us-east-1"
    trace_debug = _optional_bool(values, "TRACE_DEBUG", False)
    return Settings(
        execution_mode=mode,
        aws_enabled=aws_enabled,
        agentcore_enabled=agentcore_enabled,
        bedrock_enabled=bedrock_enabled,
        rag_provider=rag_provider,
        ai_enabled=ai_enabled,
        long_term_memory_enabled=long_term_memory_enabled,
        managed_rag_enabled=managed_rag_enabled,
        local_only_mode=local_only,
        database_url=database_url,
        model_provider=model_provider,
        bedrock_model_id=bedrock_model_id,
        aws_region=aws_region,
        trace_debug=trace_debug,
        max_agent_steps=_optional_int(values, "MAX_AGENT_STEPS", 8),
        max_tool_calls_per_turn=_optional_int(values, "MAX_TOOL_CALLS_PER_TURN", 5),
        max_model_calls_per_turn=_optional_int(values, "MAX_MODEL_CALLS_PER_TURN", 4),
        max_retrievals_per_turn=_optional_int(values, "MAX_RETRIEVALS_PER_TURN", 2),
        max_chunks_per_retrieval=_optional_int(values, "MAX_CHUNKS_PER_RETRIEVAL", 4),
        retrieval_score_floor=_optional_float(values, "RETRIEVAL_SCORE_FLOOR", 0.28),
        max_session_minutes=_optional_int(values, "MAX_SESSION_MINUTES", 20),
        max_output_tokens=_optional_int(values, "MAX_OUTPUT_TOKENS", 800),
        max_sessions_per_day=_optional_int(values, "MAX_SESSIONS_PER_DAY", 25),
        max_tool_calls_per_session=_optional_int(values, "MAX_TOOL_CALLS_PER_SESSION", 15),
        max_bedrock_input_tokens_per_call=_optional_int(
            values, "MAX_BEDROCK_INPUT_TOKENS_PER_CALL", 6000
        ),
        max_bedrock_output_tokens_per_call=_optional_int(
            values, "MAX_BEDROCK_OUTPUT_TOKENS_PER_CALL", 800
        ),
        max_memory_events_per_session=_optional_int(values, "MAX_MEMORY_EVENTS_PER_SESSION", 30),
    )


def _execution_mode(raw: str | None) -> ExecutionMode:
    if raw is None or raw.strip() == "":
        return ExecutionMode.LOCAL
    try:
        return ExecutionMode(raw.strip().lower())
    except ValueError as exc:
        raise ValueError("Invalid EXECUTION_MODE. Expected local, aws-demo, or showcase.") from exc


def _model_provider(raw: str | None) -> ModelProvider:
    if raw is None or raw.strip() == "":
        return ModelProvider.MOCK
    try:
        return ModelProvider(raw.strip().lower())
    except ValueError as exc:
        raise ValueError("Invalid MODEL_PROVIDER. Expected mock or bedrock.") from exc


def _rag_provider(raw: str | None, default: RagProvider) -> RagProvider:
    if raw is None or raw.strip() == "":
        return default
    try:
        return RagProvider(raw.strip().lower())
    except ValueError as exc:
        raise ValueError("Invalid RAG_PROVIDER. Expected local or managed.") from exc


def _optional_bool(values: Mapping[str, str], name: str, default: bool) -> bool:
    raw = values.get(name)
    if raw is None or raw.strip() == "":
        return default
    normalized = raw.strip().lower()
    if normalized in _TRUE:
        return True
    if normalized in _FALSE:
        return False
    raise ValueError(f"Invalid boolean for {name}.")


def _optional_int(values: Mapping[str, str], name: str, default: int) -> int:
    raw = values.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise ValueError(f"Invalid integer for {name}.") from exc


def _optional_float(values: Mapping[str, str], name: str, default: float) -> float:
    raw = values.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw.strip())
    except ValueError as exc:
        raise ValueError(f"Invalid number for {name}.") from exc


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    parsed: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped == "" or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key:
            parsed[key] = value
    return parsed
