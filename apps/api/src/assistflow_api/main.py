"""AssistFlow HTTP API."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from assistflow_contracts import HealthStatus
from fastapi import FastAPI
from sqlalchemy.engine import Engine

from assistflow_api.auth import install_auth
from assistflow_api.config import Settings, load_settings, validate_retrieval_settings
from assistflow_api.correlation import CorrelationMiddleware, LoggingTraceStore, metrics_snapshot
from assistflow_api.db import create_db_engine
from assistflow_api.event_queue import InMemoryEventQueue
from assistflow_api.events import ReleaseSideEffects, build_publisher, make_handler
from assistflow_api.http import register_error_handlers
from assistflow_api.logging import configure_logging
from assistflow_api.metrics import build_metrics
from assistflow_api.routes.conversations import router as conversation_router
from assistflow_api.routes.documents import router as document_router
from assistflow_api.routes.local_login import router as local_login_router
from assistflow_api.routes.preferences import router as preference_router
from assistflow_api.routes.staff import router as staff_router
from assistflow_api.routes.support import router as support_router
from assistflow_api.sqlite_lock import lock_for
from assistflow_runtime.quota import SessionQuota

configure_logging()
logger = structlog.get_logger(__name__)


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    resolved = settings if settings is not None else load_settings()
    validate_retrieval_settings(resolved)
    configure_logging()
    verifier, local_issuer = install_auth(resolved)
    owns_engine = engine is None
    resolved_engine = create_db_engine(resolved.database_url) if engine is None else engine
    sqlite_lock = lock_for(resolved_engine)
    events = InMemoryEventQueue(make_handler(resolved_engine, resolved))
    publisher = build_publisher(resolved, events)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        events.start()
        logger.info(
            "api_started",
            execution_mode=resolved.execution_mode.value,
            aws_enabled=resolved.aws_enabled,
            agentcore_enabled=resolved.agentcore_enabled,
            bedrock_enabled=resolved.bedrock_enabled,
            managed_rag_enabled=resolved.managed_rag_enabled,
            rag_provider=resolved.rag_provider.value,
            long_term_memory_enabled=resolved.long_term_memory_enabled,
            short_term_memory_enabled=resolved.short_term_memory_enabled,
            local_only_mode=resolved.local_only_mode,
            async_workers_enabled=resolved.async_workers_enabled,
            metrics_enabled=resolved.metrics_enabled,
        )
        yield
        events.stop()
        if owns_engine:
            resolved_engine.dispose()

    app = FastAPI(title="AssistFlow API", lifespan=lifespan)
    app.add_middleware(ReleaseSideEffects, queue=events)
    app.add_middleware(CorrelationMiddleware)
    app.state.settings = resolved
    app.state.trace_store = LoggingTraceStore()
    app.state.metrics = build_metrics(
        resolved.aws_enabled,
        resolved.metrics_enabled,
        resolved.aws_region,
    )
    app.state.token_verifier = verifier
    app.state.local_issuer = local_issuer
    app.state.engine = resolved_engine
    app.state.events = events
    app.state.event_publisher = publisher
    app.state.sqlite_lock = sqlite_lock
    app.state.session_quota = SessionQuota(resolved.max_sessions_per_day)
    register_error_handlers(app)
    app.include_router(local_login_router)
    app.include_router(document_router)
    app.include_router(support_router)
    app.include_router(conversation_router)
    app.include_router(preference_router)
    app.include_router(staff_router)

    @app.get("/health", response_model=HealthStatus)
    def health() -> HealthStatus:
        return HealthStatus(status="healthy")

    @app.get("/metrics")
    def metrics() -> dict[str, dict[str, float]]:
        return {"metrics": metrics_snapshot(app.state.metrics)}

    return app


app = create_app()
