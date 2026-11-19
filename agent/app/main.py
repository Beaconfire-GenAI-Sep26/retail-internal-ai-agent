import os
import re
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from shared.http import install_http, service_path, json_object
from shared.security import APIError, JWTSettings, authenticate, require_analyst, require_store
from shared.observability import bind_context
from .domain_client import DomainClient, domain_request
from .tracing import Tracing


def create_app(settings=None, domain_http=None, investigation_lookup=None, service_token=None, tracing=None):
    """B-02 supplies investigation_lookup(id) from its checkpoint repository.

    It returns {case_id, store_id}; missing ownership fails closed with 404.
    Handlers use request.state.domain_client. Only IDs go into graph checkpoints.
    """
    @asynccontextmanager
    async def lifespan(app):
        app.state.jwt = settings or JWTSettings.from_env()
        app.state.service_token = service_token or os.environ["INTERNAL_SERVICE_TOKEN"]
        app.state.domain_http = domain_http or httpx.AsyncClient(
            base_url=os.getenv("DOMAIN_SERVICE_URL", "http://domain:8000").rstrip("/") + "/", timeout=15)
        app.state.tracing = tracing if tracing is not None else Tracing.from_env()
        try:
            yield
        finally:
            await run_in_threadpool(app.state.tracing.shutdown)
            if domain_http is None:
                await app.state.domain_http.aclose()

    app = FastAPI(title="Retail Agent Service", version="0.2.0", lifespan=lifespan)

    async def authorize(request):
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
            request.state.domain_client = DomainClient(app.state.domain_http,
                access_token=request.state.access_token, settings=app.state.jwt,
                store_id=store_id, case_id=case_id, investigation_id=investigation_id,
                request_id=request.state.request_id, service_token=app.state.service_token,
                tracing=app.state.tracing)

    install_http(app, authorize, service="agent")

    @app.get("/health", tags=["health"])
    def health():
        return {"status": "ok", "service": "agent"}

    return app


app = create_app()
