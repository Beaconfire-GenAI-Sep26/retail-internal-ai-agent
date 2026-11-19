"""One error envelope for every error, as contracts.md defines:

{"error": {"code": "...", "message": "...", "details": {...}, "request_id": "..."}}
"""
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict | None = None):
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


def request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or uuid.uuid4().hex[:16]


def _envelope(request: Request, status: int, code: str, message: str, details: dict) -> JSONResponse:
    rid = request_id(request)
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "details": details, "request_id": rid}},
        headers={"X-Request-ID": rid},
    )


DEFAULT_CODES = {401: "UNAUTHENTICATED", 403: "FORBIDDEN", 404: "NOT_FOUND", 405: "NOT_FOUND"}


def install_error_handlers(app: FastAPI) -> None:
    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        request.state.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        return _envelope(request, exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        details = {"errors": [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]}
        return _envelope(request, 422, "VALIDATION_ERROR", "The request is not valid.", details)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        code = DEFAULT_CODES.get(exc.status_code, "INTERNAL")
        return _envelope(request, exc.status_code, code, str(exc.detail), {})

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        return _envelope(request, 500, "INTERNAL", "Something went wrong.", {})
