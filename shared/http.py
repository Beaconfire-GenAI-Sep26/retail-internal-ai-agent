import logging
import json
from time import perf_counter

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from shared.security import APIError
from shared.observability import (bind_context, configure_logging, context_scope,
                                  correlation_id, log_event, safe_id)

PUBLIC_PATHS = {"/health", "/ready", "/docs", "/docs/oauth2-redirect", "/openapi.json", "/redoc"}


def service_path(request):
    path = request.scope["path"]
    root = request.scope.get("root_path", "").rstrip("/")
    if root and (path == root or path.startswith(root + "/")):
        path = path[len(root):]
    return path.rstrip("/") or "/"


async def json_object(request):
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise APIError(422, "VALIDATION_ERROR", "A JSON object is required.") from None
    if not isinstance(body, dict):
        raise APIError(422, "VALIDATION_ERROR", "A JSON object is required.")
    return body


def error_response(request: Request, error: APIError) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if error.status == 401 else {}
    return JSONResponse(status_code=error.status, headers=headers, content={"error": {
        "code": error.code, "message": error.message, "details": error.details,
        "request_id": getattr(request.state, "request_id", None),
    }})


def install_http(app, authorize, *, service="application"):
    """Authenticate before routing; new business routes are protected by default."""
    configure_logging(service)
    @app.middleware("http")
    async def security_boundary(request, call_next):
        request.state.request_id = correlation_id(
            getattr(request.state, "request_id", None) or request.headers.get("X-Request-ID"))
        started = perf_counter()
        # Correlation headers carry no authority; resource scope is still checked below.
        with context_scope(service=service, request_id=request.state.request_id,
                           case_id=safe_id(request.headers.get("X-Case-ID"), "case_id"),
                           investigation_id=safe_id(request.headers.get("X-Investigation-ID"), "investigation_id"),
                           trace_id=safe_id(request.headers.get("X-Trace-ID"), "trace_id")):
            try:
                if service_path(request) not in PUBLIC_PATHS:
                    await authorize(request)
                bind_context(case_id=getattr(request.state, "case_id", None),
                             investigation_id=getattr(request.state, "investigation_id", None))
                response = await call_next(request)
            except APIError as exc:
                response = error_response(request, exc)
            except Exception as exc:
                log_event("http.unhandled_error", level=logging.ERROR, error_type=type(exc).__name__)
                response = error_response(request, APIError(500, "INTERNAL", "Internal service error."))
            # Use the route template only; never log query strings or unknown paths.
            route = request.scope.get("route")
            log_event("http.request", method=request.method, route=getattr(route, "path", "unmatched"),
                      status_code=response.status_code, duration_ms=round((perf_counter() - started) * 1000, 2),
                      case_id=getattr(request.state, "case_id", None) or safe_id(request.headers.get("X-Case-ID"), "case_id"),
                      investigation_id=getattr(request.state, "investigation_id", None) or safe_id(request.headers.get("X-Investigation-ID"), "investigation_id"))
            response.headers["X-Request-ID"] = request.state.request_id
            return response

    @app.exception_handler(APIError)
    async def api_error(request, exc):
        return error_response(request, exc)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Validation inputs can contain passwords. Never echo them.
        return error_response(request, APIError(422, "VALIDATION_ERROR", "Request validation failed."))

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return error_response(request, APIError(exc.status_code, "NOT_FOUND" if exc.status_code == 404
                                               else "HTTP_ERROR", str(exc.detail)))
