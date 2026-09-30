"""AssistFlow HTTP API."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from assistflow_contracts import HealthStatus
from fastapi import FastAPI
from sqlalchemy.engine import Engine

from assistflow_api.config import Settings, load_settings, validate_retrieval_settings
from assistflow_api.db import create_db_engine
from assistflow_api.http import register_error_handlers
from assistflow_api.logging import configure_logging
from assistflow_api.routes.conversations import router as conversation_router
from assistflow_api.routes.support import router as support_router
from assistflow_runtime.quota import SessionQuota

configure_logging()
logger = structlog.get_logger(__name__)


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    resolved = settings if settings is not None else load_settings()
    validate_retrieval_settings(resolved)
    owns_engine = engine is None
    resolved_engine = create_db_engine(resolved.database_url) if engine is None else engine

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "api_started",
            execution_mode=resolved.execution_mode.value,
            aws_enabled=resolved.aws_enabled,
            agentcore_enabled=resolved.agentcore_enabled,
            bedrock_enabled=resolved.bedrock_enabled,
            managed_rag_enabled=resolved.managed_rag_enabled,
            rag_provider=resolved.rag_provider.value,
            long_term_memory_enabled=resolved.long_term_memory_enabled,
            local_only_mode=resolved.local_only_mode,
        )
        yield
        if owns_engine:
            resolved_engine.dispose()

    app = FastAPI(title="AssistFlow API", lifespan=lifespan)
    app.state.settings = resolved
    app.state.engine = resolved_engine
    app.state.session_quota = SessionQuota(resolved.max_sessions_per_day)
    register_error_handlers(app)
    app.include_router(support_router)
    app.include_router(conversation_router)

    @app.get("/health", response_model=HealthStatus)
    def health() -> HealthStatus:
        return HealthStatus(status="healthy")

    return app


app = create_app()
