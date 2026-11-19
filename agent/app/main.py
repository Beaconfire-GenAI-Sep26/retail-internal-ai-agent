"""The Agent Service app. Run with `uv run uvicorn app.main:app`."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from langgraph.checkpoint.memory import InMemorySaver

from app.api import investigations
from app.config import Settings, get_settings
from app.domain.client import DomainClient, HttpDomainClient
from app.domain.fixtures import FixtureDomainClient
from app.errors import install_error_handlers
from app.graph.build import build_graph
from app.ids import IdFactory, UlidIdFactory
from app.llm.base import ReasonModel
from app.logs import configure_logging, request_id_var
from app.runner import Runner
from app.store import InvestigationStore


def make_domain_client(settings: Settings) -> DomainClient:
    if settings.agent_domain_mode == "fixtures":
        return FixtureDomainClient(settings.agent_fixtures_dir)
    return HttpDomainClient(
        settings.domain_service_url,
        settings.internal_service_token,
        timeout=settings.domain_timeout_seconds,
        max_retries=settings.agent_max_retries,
    )


def make_model(settings: Settings) -> ReasonModel:
    from app.llm.anthropic_model import AnthropicReasonModel

    return AnthropicReasonModel(settings)


def create_app(
    settings: Settings | None = None,
    *,
    domain_client: DomainClient | None = None,
    model: ReasonModel | None = None,
    ids: IdFactory | None = None,
    configure_logs: bool = True,
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if configure_logs:
            configure_logging(settings.log_level)
        if settings.agent_checkpointer != "memory":
            raise RuntimeError("The Postgres checkpointer arrives in M2. Set AGENT_CHECKPOINTER=memory for now.")
        domain = domain_client or make_domain_client(settings)
        reason_model = model or make_model(settings)
        graph = build_graph(InMemorySaver())
        store = InvestigationStore()
        app.state.settings = settings
        app.state.domain_client = domain
        app.state.graph = graph
        app.state.store = store
        app.state.ids = ids or UlidIdFactory()
        app.state.runner = Runner(graph=graph, store=store, settings=settings, domain_client=domain,
                                  model=reason_model, ids=app.state.ids)
        yield
        await app.state.runner.shutdown()
        await domain.aclose()

    # The gateway prefix (ROOT_PATH, /agent) is passed to uvicorn as --root-path; see the Dockerfile.
    app = FastAPI(title="Retail Agent Service", version="0.1.0", lifespan=lifespan)
    install_error_handlers(app)

    @app.middleware("http")
    async def request_id(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        return response

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "agent"}

    @app.get("/ready", tags=["health"])
    async def ready(request: Request) -> Any:
        s: Settings = request.app.state.settings
        checks = {"model": "configured" if s.anthropic_api_key else "missing ANTHROPIC_API_KEY",
                  "checkpointer": s.agent_checkpointer}
        ok = bool(s.anthropic_api_key)
        if s.agent_domain_mode == "fixtures":
            checks["domain"] = "fixtures"
        else:
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    resp = await client.get(s.domain_service_url.rstrip("/") + "/health")
                checks["domain"] = "ok" if resp.status_code == 200 else f"http {resp.status_code}"
                ok = ok and resp.status_code == 200
            except httpx.HTTPError:
                checks["domain"] = "unreachable"
                ok = False
        return JSONResponse(status_code=200 if ok else 503, content={"status": "ok" if ok else "not_ready", **checks})

    app.include_router(investigations.router)
    return app


app = create_app()
