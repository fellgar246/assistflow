"""Map support errors onto one JSON problem body."""

import structlog
from assistflow_customers.errors import SupportError
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.requests import Request

logger = structlog.get_logger(__name__)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(SupportError)
    def support_error(_request: Request, exc: SupportError) -> JSONResponse:
        return _problem(exc.status_code, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    def invalid_request(_request: Request, _exc: RequestValidationError) -> JSONResponse:
        return _problem(422, "invalid_request", "The request is invalid.")

    @app.exception_handler(HTTPException)
    def http_error(_request: Request, exc: HTTPException) -> JSONResponse:
        message = (
            exc.detail if isinstance(exc.detail, str) else "The request could not be completed."
        )
        return _problem(exc.status_code, "http_error", message)

    @app.exception_handler(Exception)
    def unhandled(_request: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled_error", error_type=type(exc).__name__)
        return _problem(500, "internal_error", "The request could not be completed.")


def _problem(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"code": code, "message": message})
