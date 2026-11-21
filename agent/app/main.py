"""JWT-protected B-02 workflow. Run agent.app.main:app from the repository root."""

from __future__ import annotations

import re
from starlette.concurrency import run_in_threadpool

from shared.http import install_http, service_path, json_object
from shared.observability import bind_context, correlation_id
from agent.app.tracing import Tracing
from shared.security import APIError, JWTSettings, authenticate, require_analyst, require_store
from agent.app.domain_client import DomainClient as ScopedDomainClient, domain_request
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from langgraph.checkpoint.memory import InMemorySaver

from agent.app.api import investigations
from agent.app.config import Settings, get_settings
from agent.app.domain.client import DomainClient, DomainError, HttpDomainClient
from agent.app.domain.fixtures import FixtureDomainClient
from agent.app.errors import install_error_handlers
from agent.app.graph.build import build_graph
from agent.app.ids import UlidIdFactory
from agent.app.llm.base import ReasonModel
from agent.app.logs import configure_logging, request_id_var
from agent.app.persistence import open_postgres, restore_index
from agent.app.runner import Runner
from agent.app.store import InvestigationStore


def make_domain_client(settings: Settings, *, tracing=None) -> DomainClient:
    if settings.agent_domain_mode == "fixtures":
        return FixtureDomainClient(settings.agent_fixtures_dir)
    return HttpDomainClient(
        settings.domain_service_url,
        settings.internal_service_token,
        timeout=settings.domain_timeout_seconds,
        max_retries=settings.agent_max_retries,
        jwt_settings=JWTSettings(settings.jwt_secret, settings.jwt_issuer),
        tracing=tracing,
    )


def make_model(settings: Settings, *, tracing=None) -> ReasonModel:
    from agent.app.llm.anthropic_model import AnthropicReasonModel

    if not settings.anthropic_api_key:
        class UnconfiguredModel:
            name = "anthropic"
            configured = False
            async def reason(self, prompt, state):
                from agent.app.llm.base import ModelError
                raise ModelError("UPSTREAM_UNAVAILABLE", "ANTHROPIC_API_KEY is not configured.")
        return UnconfiguredModel()
    return AnthropicReasonModel(settings, tracing=tracing)


def create_app(
    settings=None, domain_http=None, investigation_lookup=None, service_token=None,
    *, domain_client=None, model=None, ids=None, configure_logs=True, tracing=None, checkpointer=None,
) -> FastAPI:
    # Keep the A-02 injectable boundary for policy tests/extensions while the
    # default app runs the actual B-02 graph and investigation API.
    jwt_override = settings if isinstance(settings, JWTSettings) else None
    workflow = jwt_override is None and domain_http is None and investigation_lookup is None
    runtime_settings = (Settings(_env_file=None, jwt_secret=jwt_override.secret,
                                 jwt_issuer=jwt_override.issuer)
                        if jwt_override else settings or get_settings())

    @asynccontextmanager
    async def lifespan(app):
        app.state.jwt = jwt_override or JWTSettings(runtime_settings.jwt_secret, runtime_settings.jwt_issuer)
        app.state.tracing = tracing if tracing is not None else Tracing.from_env()
        app.state.settings = runtime_settings
        app.state.service_token = service_token or runtime_settings.internal_service_token
        pool = None
        if workflow:
            if configure_logs:
                configure_logging(runtime_settings.log_level)
            if checkpointer is not None:
                saver = checkpointer
            elif runtime_settings.agent_checkpointer == "postgres":
                saver, pool = await open_postgres(runtime_settings)
            else:
                saver = InMemorySaver()
            domain = domain_client or make_domain_client(runtime_settings, tracing=app.state.tracing)
            reason_model = model or make_model(runtime_settings, tracing=app.state.tracing)
            graph = build_graph(saver)
            app.state.domain_client = domain
            app.state.graph = graph
            app.state.store = InvestigationStore()
            await restore_index(graph, app.state.store, saver, pool)  # empty for a fresh in-memory saver
            app.state.ids = ids or UlidIdFactory()
            app.state.runner = Runner(graph=graph, store=app.state.store, settings=runtime_settings,
                domain_client=domain, model=reason_model, ids=app.state.ids, tracing=app.state.tracing)
        else:
            app.state.domain_http = domain_http or httpx.AsyncClient(
                base_url=runtime_settings.domain_service_url.rstrip("/")+"/", timeout=15)
        try:
            yield
        finally:
            if workflow:
                await app.state.runner.shutdown()
                await domain.aclose()
                client = getattr(reason_model, "client", None)
                if client is not None:
                    await client.close()
                if pool is not None:
                    await pool.close()
            elif domain_http is None:
                await app.state.domain_http.aclose()
            await run_in_threadpool(app.state.tracing.shutdown)

    app = FastAPI(title="Retail Agent Service", version="0.2.0", lifespan=lifespan)
    install_error_handlers(app)
    async def authorize_legacy(request):
        user = authenticate(request, app.state.jwt)
        path, method = service_path(request), request.method
        request.state.store_ids = tuple(user.store_ids)
        if method not in {"GET", "POST"}:
            raise APIError(403, "FORBIDDEN", "Operation is not permitted.")
        if method == "POST":
            require_analyst(user)
        case_id = None
        investigation_id = None
        if path == "/investigations":
            if method == "POST":
                body = await json_object(request)
                case_id = body.get("case_id")
            else:
                case_id = request.query_params.get("case_id")
            if not isinstance(case_id, str) or not re.fullmatch(r"CASE-\d{4,}", case_id):
                raise APIError(422, "VALIDATION_ERROR", "A valid case_id is required.")
        elif match := re.fullmatch(r"/investigations/([A-Za-z0-9-]+)(/resume)?", path):
            if (method == "POST") != bool(match[2]):
                raise APIError(403, "FORBIDDEN", "Operation is not permitted.")
            investigation_id = match[1]
            context = await run_in_threadpool(investigation_lookup, investigation_id) if investigation_lookup else None
            if context is None:
                raise APIError(404, "NOT_FOUND", "Investigation not found.")
            case_id = context["case_id"]
            require_store(user, context["store_id"], hide=method == "GET")
        else:
            raise APIError(403, "FORBIDDEN", "Operation has no access policy.")

        # Domain resolves the authoritative case -> store mapping using the same JWT.
        request.state.case_id = case_id
        request.state.investigation_id = investigation_id
        bind_context(case_id=case_id, investigation_id=investigation_id)
        case = await domain_request(app.state.domain_http, "GET", f"/cases/{case_id}", headers={
            "Authorization": f"Bearer {request.state.access_token}", "X-Request-ID": request.state.request_id,
            "X-Case-ID": case_id,
            **({"X-Investigation-ID": investigation_id} if investigation_id else {}),
        })
        store_id = case["store_id"]
        require_store(user, store_id, hide=method == "GET")
        if investigation_id and context["store_id"] != store_id:
            raise APIError(403, "STORE_NOT_PERMITTED", "Investigation and case store do not match.")
        request.state.case_id, request.state.store_id = case_id, store_id
        # Start handlers bind the new investigation ID after generating it. Resumes
        # use this fresh request's JWT, never a token from persisted graph state.
        if investigation_id:
            request.state.domain_client = ScopedDomainClient(app.state.domain_http,
                access_token=request.state.access_token, settings=app.state.jwt,
                store_id=store_id, case_id=case_id, investigation_id=investigation_id,
                request_id=request.state.request_id, service_token=app.state.service_token,
                tracing=app.state.tracing)


    async def authorize(request):
        if not workflow:
            return await authorize_legacy(request)
        user = authenticate(request, app.state.jwt)
        request.state.store_ids = tuple(user.store_ids)
        path, method = service_path(request), request.method
        if method == "POST":
            require_analyst(user)
        if path == "/investigations" and method in {"GET", "POST"}:
            return  # endpoint resolves the case using this user's forwarded JWT
        match = re.fullmatch(r"/investigations/([A-Za-z0-9-]+)(/resume)?", path)
        if not match or (method == "POST") != bool(match[2]) or method not in {"GET", "POST"}:
            raise APIError(403, "FORBIDDEN", "Operation has no access policy.")
        row = app.state.store.get(match[1])
        if row is None:
            raise APIError(404, "NOT_FOUND", "Investigation not found.")
        require_store(user, row.store_id, hide=method == "GET")
        domain = app.state.domain_client.bind(token=request.state.access_token,
            request_id=request.state.request_id, investigation_id=row.investigation_id,
            store_id=row.store_id, case_id=row.case_id, max_retries=0)
        try:
            case = await domain.get_case(row.case_id)
        except DomainError as exc:
            status = 404 if exc.status in {403, 404} else exc.status
            raise APIError(status, "NOT_FOUND" if status == 404 else exc.code,
                           "Investigation not found." if status == 404 else exc.message) from None
        require_store(user, case.store_id, hide=method == "GET")
        if case.store_id != row.store_id:
            raise APIError(403, "STORE_NOT_PERMITTED", "Investigation and case store do not match.")
        request.state.case_id, request.state.store_id = row.case_id, row.store_id
        request.state.investigation_id = row.investigation_id

    install_http(app, authorize, service="agent")

    @app.middleware("http")
    async def request_id(request, call_next):
        rid = correlation_id(request.headers.get("X-Request-ID"))
        request.state.request_id = rid
        token = request_id_var.set(rid)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        return response

    @app.get("/health", tags=["health"])
    async def health():
        return {"status": "ok", "service": "agent"}

    @app.get("/ready", tags=["health"])
    async def ready():
        configured = not workflow or getattr(app.state.runner.model, "configured", True)
        checks = {"model": "configured" if configured else "missing ANTHROPIC_API_KEY"}
        if workflow:
            checks["checkpointer"] = runtime_settings.agent_checkpointer
            checks["domain"] = "fixtures"
            if runtime_settings.agent_domain_mode == "http":
                try:
                    async with httpx.AsyncClient(timeout=3) as client:
                        response = await client.get(runtime_settings.domain_service_url.rstrip("/") + "/health")
                    checks["domain"] = "ok" if response.status_code == 200 else "unavailable"
                except httpx.HTTPError:
                    checks["domain"] = "unavailable"
                configured = configured and checks["domain"] == "ok"
        return JSONResponse(status_code=200 if configured else 503,
            content={"status": "ok" if configured else "not_ready", "service": "agent", **checks})

    if workflow:
        app.include_router(investigations.router)
    return app


app = create_app()
