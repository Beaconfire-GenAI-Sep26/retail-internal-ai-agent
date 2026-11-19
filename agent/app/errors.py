"""The contracts error envelope and the investigation error codes."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.logs import log_event, request_id_var

logger = logging.getLogger("agent.errors")

# Codes an investigation's `error.code` can take (InvestigationView.error).
UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
UNAUTHENTICATED = "UNAUTHENTICATED"
INTERNAL = "INTERNAL"
DOMAIN_REJECTED = "DOMAIN_REJECTED"
MODEL_REFUSED = "MODEL_REFUSED"
MODEL_TRUNCATED = "MODEL_TRUNCATED"
RUN_TIMEOUT = "RUN_TIMEOUT"
AGENT_RESTARTED = "AGENT_RESTARTED"

_HTTP_CODES = {
    400: "VALIDATION_ERROR",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
}


class AppError(Exception):
    """An error returned to the caller in the contracts envelope."""

    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


def error_body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": request_id_var.get(),
        }
    }


def _response(status: int, code: str, message: str, details: dict[str, Any] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content=error_body(code, message, details))


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return _response(exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        problems = [
            {"loc": [str(p) for p in err.get("loc", ())], "msg": err.get("msg", "")} for err in exc.errors()
        ]
        return _response(422, "VALIDATION_ERROR", "The request body or query is invalid.", {"errors": problems})

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "INTERNAL" if exc.status_code >= 500 else "ERROR")
        message = exc.detail if isinstance(exc.detail, str) else code
        return _response(exc.status_code, code, message)

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        log_event(logger, logging.ERROR, "unhandled error", error_type=type(exc).__name__)
        logger.exception("unhandled error")
        return _response(500, INTERNAL, "Something went wrong. Details are in the service log.")
