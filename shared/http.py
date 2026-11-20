import logging
import json
from uuid import uuid4

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from shared.security import APIError

logger = logging.getLogger(__name__)
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


def install_http(app, authorize):
    """Authenticate before routing; new business routes are protected by default."""
    @app.middleware("http")
    async def security_boundary(request, call_next):
        request_id = getattr(request.state, "request_id", None) or request.headers.get("X-Request-ID", "")
        request.state.request_id = request_id if 0 < len(request_id) <= 128 else uuid4().hex
        try:
            if service_path(request) not in PUBLIC_PATHS:
                await authorize(request)
            response = await call_next(request)
        except APIError as exc:
            response = error_response(request, exc)
        except Exception:
            # Do not log bodies, Authorization headers or refresh cookies.
            logger.error("Unhandled service error request_id=%s", request.state.request_id)
            response = error_response(request, APIError(500, "INTERNAL", "Internal service error."))
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
