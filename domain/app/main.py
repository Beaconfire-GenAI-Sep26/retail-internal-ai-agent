import logging
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text, bindparam
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from shared.database import database_engine
from shared.http import error_response, install_http
from shared.security import APIError, JWTSettings
from .access import DomainAccess

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.jwt = app.state.jwt_override or JWTSettings.from_env()
    app.state.engine = app.state.engine_override if app.state.engine_override is not None else database_engine()
    app.state.service_token = app.state.service_token_override or os.environ["INTERNAL_SERVICE_TOKEN"]
    app.state.access = DomainAccess(app.state.engine)
    session_engine = app.state.engine.execution_options(schema_translate_map={"domain": None, "eval": None}) \
        if app.state.engine.dialect.name == "sqlite" else app.state.engine
    app.state.session_factory = sessionmaker(bind=session_engine, autoflush=False, expire_on_commit=False)
    try:
        yield
    finally:
        if app.state.engine_override is None:
            app.state.engine.dispose()


def create_app(engine=None, settings=None, service_token=None, *, business_routes=True):
    app = FastAPI(title="Retail Domain Service", version="0.2.0", lifespan=lifespan)
    app.state.engine_override = engine
    app.state.jwt_override = settings
    app.state.service_token_override = service_token

    async def authorize(request):
        await request.app.state.access.authorize(request)

    install_http(app, authorize, service="domain")

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        return error_response(request, APIError(503, "UPSTREAM_UNAVAILABLE", "Domain storage unavailable."))

    app.add_api_route("/health", health, methods=["GET"], tags=["health"])
    app.add_api_route("/ready", ready, methods=["GET"], tags=["health"])
    app.add_api_route("/stores/{store_id}", store, methods=["GET"])
    app.add_api_route("/stores/{store_id}/menu", menu, methods=["GET"])
    if business_routes:
        from .routers import cases, catalog, evidence, internal, monitor, proposals, stores
        from .errors import ApiError
        app.include_router(cases.router)
        app.include_router(evidence.router)
        app.include_router(monitor.router)
        app.include_router(proposals.router)  # C-03
        app.include_router(catalog.router)  # C-03
        app.include_router(internal.router)  # C-03, agent only
        # Preserve the existing lightweight store/menu reads; include all C-02 diagnostics.
        for route in stores.router.routes:
            if route.path not in {"/stores/{store_id}", "/stores/{store_id}/menu"}:
                app.router.routes.append(route)

        @app.exception_handler(ApiError)
        async def domain_error(request, exc):
            return error_response(request, exc)
    return app


def health() -> dict[str, str]:
    return {"status": "ok", "service": "domain"}


def ready(request: Request) -> JSONResponse:
    try:
        with request.app.state.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.warning("PostgreSQL readiness check failed")
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "service": "domain", "database": "unavailable"},
        )
    return JSONResponse(
        content={"status": "ok", "service": "domain", "database": "ok"},
    )


def store(store_id: str, request: Request):
    schema = request.app.state.access.schema
    with request.app.state.engine.connect() as conn:
        row = conn.execute(text(f"SELECT store_id, name, city, timezone, cuisine FROM {schema}stores "
                                "WHERE store_id = :store_id"), {"store_id": store_id}).mappings().first()
    if row is None:
        raise APIError(404, "NOT_FOUND", "Store not found.")
    return dict(row)


def menu(store_id: str, request: Request):
    store(store_id, request)
    schema = request.app.state.access.schema
    with request.app.state.engine.connect() as conn:
        rows = conn.execute(text(f"SELECT item_id, store_id, name, category, price, available_modifiers "
                                 f"FROM {schema}menu_items WHERE store_id = :store_id ORDER BY item_id LIMIT 200"),
                            {"store_id": store_id}).mappings().all()
    # Text SQL doesn't apply SQLAlchemy's JSON processor on SQLite (used by tests).
    return [{**dict(row), "available_modifiers": json.loads(row["available_modifiers"])
             if isinstance(row["available_modifiers"], str) else row["available_modifiers"]} for row in rows]


def scoped_case_query(request: Request, *, status=None, store_id=None):
    """C-02 case list handlers use this query before serialization to CaseSummary."""
    schema = request.app.state.access.schema
    filters = ["store_id IN :store_ids"]
    params = {"store_ids": request.state.store_ids}
    for name, value in (("store_id", store_id), ("status", status)):
        if value is not None:
            filters.append(f"{name} = :{name}")
            params[name] = value
    statement = text(f"SELECT * FROM {schema}cases WHERE {' AND '.join(filters)} "
                     "ORDER BY opened_at DESC LIMIT 200")
    return statement.bindparams(bindparam("store_ids", expanding=True)), params


app = create_app()
