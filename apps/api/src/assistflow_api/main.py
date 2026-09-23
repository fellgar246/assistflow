"""AssistFlow HTTP API."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from assistflow_contracts import HealthStatus
from fastapi import FastAPI

from assistflow_api.config import Settings, load_settings
from assistflow_api.logging import configure_logging

configure_logging()
logger = structlog.get_logger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings if settings is not None else load_settings()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "api_started",
            execution_mode=resolved.execution_mode.value,
            aws_enabled=resolved.aws_enabled,
            agentcore_enabled=resolved.agentcore_enabled,
            bedrock_enabled=resolved.bedrock_enabled,
            managed_rag_enabled=resolved.managed_rag_enabled,
            long_term_memory_enabled=resolved.long_term_memory_enabled,
            local_only_mode=resolved.local_only_mode,
        )
        yield

    app = FastAPI(title="AssistFlow API", lifespan=lifespan)
    app.state.settings = resolved

    @app.get("/health", response_model=HealthStatus)
    def health() -> HealthStatus:
        return HealthStatus(status="healthy")

    return app


app = create_app()
