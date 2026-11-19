import os
import time
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from shared.database import database_engine
from shared.http import error_response, install_http, service_path
from shared.security import APIError, JWTSettings, authenticate, issue_token, unauthenticated
from .repository import AuthRepository

COOKIE = "refresh_token"
COOKIE_PATH = "/auth"


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=1024)


def create_app(engine=None, settings=None, *, seed=None, cookie_secure=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.jwt = settings or JWTSettings.from_env()
        app.state.engine = engine if engine is not None else database_engine()
        app.state.repo = AuthRepository(app.state.engine)
        app.state.repo.initialize()
        should_seed = seed if seed is not None else os.getenv("SEED_AUTH_ACCOUNTS", "false").lower() == "true"
        if should_seed:
            app.state.repo.seed(os.environ["SEED_ANALYST_PASSWORD"], os.environ["SEED_VIEWER_PASSWORD"])
        try:
            yield
        finally:
            if engine is None:
                app.state.engine.dispose()

    app = FastAPI(title="Retail Auth Service", version="0.2.0", lifespan=lifespan)
    secure = cookie_secure if cookie_secure is not None else os.getenv("COOKIE_SECURE", "true").lower() == "true"
    refresh_days = int(os.getenv("REFRESH_TTL_DAYS", "7"))
    if refresh_days <= 0:
        raise ValueError("REFRESH_TTL_DAYS must be positive")

    def check_origin(request):
        if request.headers.get("sec-fetch-site") == "cross-site":
            raise APIError(403, "FORBIDDEN", "Cross-site authentication request denied.")
        origin = request.headers.get("origin")
        if origin:
            expected = os.getenv("PUBLIC_ORIGIN") or f"{request.url.scheme}://{request.url.netloc}"
            if origin.rstrip("/") != expected.rstrip("/") or urlsplit(origin).scheme not in {"http", "https"}:
                raise APIError(403, "FORBIDDEN", "Cross-site authentication request denied.")

    async def authorize(request):
        if service_path(request) in {"/login", "/refresh", "/logout"}:
            check_origin(request)
        else:
            authenticate(request, app.state.jwt)

    install_http(app, authorize, service="auth")

    @app.middleware("http")
    async def no_cache(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        return error_response(request, APIError(503, "UPSTREAM_UNAVAILABLE", "Authentication storage unavailable."))

    def set_cookie(response, raw, expires):
        response.set_cookie(COOKIE, raw, max_age=max(0, expires - int(time.time())),
                            httponly=True, secure=secure, samesite="lax", path=COOKIE_PATH)

    def clear_cookie(response):
        response.delete_cookie(COOKIE, path=COOKIE_PATH, httponly=True, secure=secure, samesite="lax")

    @app.get("/health", tags=["health"])
    def health():
        return {"status": "ok", "service": "auth"}

    @app.get("/ready", tags=["health"])
    def ready():
        with app.state.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "service": "auth", "database": "ok"}

    @app.post("/login")
    def login(body: LoginRequest, request: Request, response: Response):
        user = app.state.repo.login(body.username, body.password)
        payload = issue_token(user, app.state.jwt)
        app.state.repo.revoke(request.cookies.get(COOKIE))
        raw, expires = app.state.repo.create_session(user, refresh_days)
        set_cookie(response, raw, expires)
        return payload

    @app.get("/me")
    def me(request: Request):
        return app.state.repo.current_user(request.state.user.user_id)

    @app.post("/refresh")
    async def refresh(request: Request):
        raw = request.cookies.get(COOKIE)
        try:
            if not raw or len(raw) > 512:
                raise unauthenticated()
            user, replacement, expires = await run_in_threadpool(app.state.repo.rotate, raw)
        except APIError as exc:
            response = error_response(request, exc)
            clear_cookie(response)
            return response
        response = JSONResponse(issue_token(user, app.state.jwt))
        set_cookie(response, replacement, expires)
        return response

    @app.post("/logout", status_code=204)
    def logout(request: Request):
        app.state.repo.revoke(request.cookies.get(COOKIE))
        response = Response(status_code=204)
        clear_cookie(response)
        return response

    return app


app = create_app()
