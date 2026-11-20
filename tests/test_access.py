import asyncio
import time

import httpx
import jwt
import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from domain.app.main import create_app as domain_app, scoped_case_query
from agent.app.main import create_app as agent_app
from agent.app.domain_client import DomainClient
from shared.security import APIError

SERVICE_TOKEN = "test-internal-service-token"


@pytest.fixture
def domain(domain_engine, settings):
    app = domain_app(domain_engine, settings, SERVICE_TOKEN, business_routes=False)
    app.state.calls = []

    # Probe handlers exercise A-02 policy without implementing C-03 decisions,
    # dispatch, diagnostics or B-02 investigation business logic in this task.
    @app.get("/cases")
    def cases(request: Request, store_id: str = None):
        query, params = scoped_case_query(request, store_id=store_id)
        with domain_engine.connect() as conn:
            return [dict(row) for row in conn.execute(query, params).mappings()]

    @app.get("/cases/{case_id}")
    def case(case_id: str, request: Request):
        return {"case_id": case_id, "store_id": request.state.store_id}

    def probe(request: Request):
        app.state.calls.append(request.url.path)
        return {"user_id": request.state.user.user_id, "store_id": request.state.store_id}

    for path, methods in [
        ("/proposals/{proposal_id}", ["GET"]),
        ("/proposals/{proposal_id}/decision", ["POST"]),
        ("/proposals/{proposal_id}/versions", ["POST"]),
        ("/proposals/{proposal_id}/merchant-reply", ["POST"]),
        ("/rechecks/{recheck_id}/run", ["POST"]),
        ("/stores/{store_id}/diagnostics/claim-breakdown", ["POST"]),
        ("/internal/cases/{case_id}/proposals", ["POST"]),
        ("/internal/cases/{case_id}/investigation", ["PUT"]),
        ("/evidence/{evidence_id}", ["GET"]),
        ("/evidence/resolve", ["POST"]),
    ]:
        app.add_api_route(path, probe, methods=methods)
    return app


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize("service", ["domain", "agent", "auth"])
@pytest.mark.parametrize("invalid", ["missing", "malformed", "expired", "signature", "issuer", "algorithm", "no_exp", "no_sub", "role", "grants", "future_iat", "string_exp"])
def test_credentials_rejected_everywhere(service, invalid, domain, engine, settings, identities):
    from auth.app.main import create_app as auth_app
    claims = jwt.decode(identities(), settings.secret, algorithms=["HS256"], issuer=settings.issuer)
    secret, algorithm = settings.secret, "HS256"
    if invalid == "expired":
        claims.update(iat=int(time.time()) - 120, exp=int(time.time()) - 1)
    elif invalid == "signature": secret = "a-different-key-at-least-thirty-two-bytes"
    elif invalid == "issuer": claims["iss"] = "attacker"
    elif invalid == "algorithm": algorithm = "HS384"
    elif invalid == "no_exp": del claims["exp"]
    elif invalid == "no_sub": del claims["sub"]
    elif invalid == "role": claims["role"] = "admin"
    elif invalid == "grants": claims["store_ids"] = "STORE-A"
    elif invalid == "future_iat": claims["iat"] = int(time.time()) + 86400
    elif invalid == "string_exp": claims["exp"] = str(claims["exp"])
    token = jwt.encode(claims, secret, algorithm=algorithm)
    headers = {} if invalid == "missing" else bearer("not.a.jwt" if invalid == "malformed" else token)
    app, path = (domain, "/domain/stores/STORE-A") if service == "domain" else (
        (agent_app(settings, domain_http=httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500))), service_token=SERVICE_TOKEN), "/agent/investigations?case_id=CASE-0001")
        if service == "agent" else (auth_app(engine, settings, seed=False), "/auth/me"))
    with TestClient(app, root_path=f"/{service}") as client:
        response = client.get(path, headers=headers)
    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_viewer_store_reads_and_list_filtering(domain, identities):
    with TestClient(domain, root_path="/domain") as client:
        headers = bearer(identities("viewer", ["STORE-A"]))
        assert client.get("/domain/stores/STORE-A", headers=headers).status_code == 200
        assert client.get("/domain/stores/STORE-B", headers=headers).status_code == 403
        assert [row["store_id"] for row in client.get("/domain/cases", headers=headers).json()] == ["STORE-A"]
        assert client.get("/domain/cases?store_id=STORE-B", headers=headers).json() == []
        assert client.get("/domain/cases/CASE-0002", headers=headers).status_code == 404
        assert client.get("/domain/proposals/PROP-0002", headers=headers).status_code == 404
        assert client.get("/domain/evidence/EV-CLM-000002", headers=headers).status_code == 404
        assert client.post("/domain/stores/STORE-A/diagnostics/claim-breakdown", headers=headers, json={}).status_code == 200


@pytest.mark.parametrize("path", ["/proposals/PROP-0001/decision", "/proposals/PROP-0001/versions", "/proposals/PROP-0001/merchant-reply", "/rechecks/RCK-0001/run", "/monitor/run", "/dispatch"])
def test_viewer_cannot_mutate_or_dispatch(domain, identities, path):
    with TestClient(domain, root_path="/domain") as client:
        response = client.post("/domain" + path, headers=bearer(identities("viewer", ["STORE-A"])), json={})
    assert response.status_code == 403
    assert domain.state.calls == []


def test_analyst_decides_only_stored_proposal_store(domain, identities):
    with TestClient(domain, root_path="/domain") as client:
        headers = bearer(identities())
        assert client.post("/domain/proposals/PROP-0001/decision", headers=headers, json={}).status_code == 200
        # A caller-supplied permitted store cannot change PROP-0003's ownership.
        result = client.post("/domain/proposals/PROP-0003/decision?store_id=STORE-A",
                             headers={**headers, "X-User-Role": "admin", "X-Store-ID": "STORE-A"},
                             json={"store_id": "STORE-A", "role": "loe_analyst"})
        assert result.status_code == 403
    assert len(domain.state.calls) == 1


def test_internal_requires_both_credentials_and_narrow_scope(domain, identities):
    with TestClient(domain, root_path="/domain") as client:
        path = "/domain/internal/cases/CASE-0001/proposals"
        context = {"X-Service-Token": SERVICE_TOKEN, "X-Store-ID": "STORE-A", "X-Investigation-ID": "INV-TEST"}
        assert client.post(path, headers=context, json={}).status_code == 401
        assert client.post(path, headers=bearer(identities()), json={}).status_code == 403
        headers = {**bearer(identities()), **context}
        assert client.post(path, headers=headers, json={}).status_code == 200
        assert client.post(path.replace("0001", "0003"), headers=headers, json={}).status_code == 403
        assert client.post(path, headers={**headers, "X-Store-ID": "STORE-B"}, json={}).status_code == 403
        assert client.post(path, headers={**headers, **bearer(identities("viewer", ["STORE-A"]))}, json={}).status_code == 403


def test_domain_client_preserves_jwt_and_cannot_broaden(domain, identities, settings):
    async def run():
        token = identities()
        seen = []
        async def capture(request):
            seen.append(request)
            return httpx.Response(200, json={"ok": True})
        async with httpx.AsyncClient(base_url="http://domain/", transport=httpx.MockTransport(capture)) as http:
            client = DomainClient(http, access_token=token, settings=settings, store_id="STORE-A", case_id="CASE-0001",
                                  investigation_id="INV-TEST", request_id="request-test", service_token=SERVICE_TOKEN)
            await client.request("GET", "/stores/STORE-A/menu")
            await client.request("POST", "/internal/cases/CASE-0001/proposals", json={"investigation_id": "INV-TEST"})
            for method, path in [("GET", "/stores/STORE-B/menu"), ("GET", "/cases/CASE-0002"),
                                 ("POST", "/proposals/PROP-0001/decision"), ("POST", "/dispatch"),
                                 ("GET", "http://attacker/token"), ("GET", "/stores/STORE-A/../STORE-B"),
                                 ("GET", "/stores/STORE-A%2f..%2fSTORE-B")]:
                with pytest.raises(APIError) as exc:
                    await client.request(method, path)
                assert exc.value.status == 403
            with pytest.raises(APIError):
                await client.request("POST", "/internal/cases/CASE-0001/proposals", json={"investigation_id": "INV-OTHER"})
        assert len(seen) == 2
        assert all(r.headers["Authorization"] == f"Bearer {token}" and r.headers["X-Store-ID"] == "STORE-A" for r in seen)
        assert seen[1].headers["X-Service-Token"] == SERVICE_TOKEN
        assert seen[1].headers["X-Investigation-ID"] == "INV-TEST"
        assert seen[1].headers["X-Request-ID"] == "request-test"
    asyncio.run(run())


def test_real_agent_to_domain_transport_rechecks_scope(domain, identities, settings):
    async def run():
        async with domain.router.lifespan_context(domain):
            async with httpx.AsyncClient(base_url="http://domain/", transport=httpx.ASGITransport(app=domain)) as http:
                client = DomainClient(http, access_token=identities(), settings=settings, store_id="STORE-A",
                                      case_id="CASE-0001", investigation_id="INV-TEST", request_id="trace", service_token=SERVICE_TOKEN)
                assert (await client.request("GET", "/stores/STORE-A"))["store_id"] == "STORE-A"
                assert (await client.request("POST", "/internal/cases/CASE-0001/proposals", json={}))["user_id"] == "USR-001"
                # Even another store in this JWT is outside this bound call.
                with pytest.raises(APIError) as exc:
                    await client.request("GET", "/proposals/PROP-0002")
                assert exc.value.status == 403
    asyncio.run(run())


def test_agent_start_resume_and_read_authorization(settings, identities):
    async def upstream(request):
        number = request.url.path.rsplit("-", 1)[-1]
        return httpx.Response(200, json={"store_id": {"0001": "STORE-A", "0002": "STORE-B", "0003": "STORE-C"}[number]})
    http = httpx.AsyncClient(base_url="http://domain/", transport=httpx.MockTransport(upstream))
    app = agent_app(settings, http, lambda _: {"case_id": "CASE-0002", "store_id": "STORE-B"}, SERVICE_TOKEN)
    @app.post("/investigations")
    def start(request: Request):
        return {"store_id": request.state.store_id}
    @app.get("/investigations/{investigation_id}")
    def read(request: Request):
        return {"store_id": request.state.store_id}
    @app.post("/investigations/{investigation_id}/resume")
    def resume(request: Request):
        return {"store_id": request.state.domain_client.store_id}
    with TestClient(app, root_path="/agent") as client:
        viewer, analyst = bearer(identities("viewer", ["STORE-A"])), bearer(identities())
        assert client.post("/agent/investigations", headers=viewer, json={"case_id": "CASE-0001"}).status_code == 403
        assert client.post("/agent/investigations", headers=analyst, json={"case_id": "CASE-0001"}).status_code == 200
        assert client.post("/agent/investigations", headers=analyst, json={"case_id": "CASE-0003", "store_id": "STORE-A"}).status_code == 403
        assert client.get("/agent/investigations/INV-TEST", headers=viewer).status_code == 404
        assert client.post("/agent/investigations/INV-TEST/resume", headers=viewer).status_code == 403
        assert client.post("/agent/investigations/INV-TEST/resume", headers=analyst).json()["store_id"] == "STORE-B"
        assert client.post("/agent/investigations", headers=analyst, content="{").status_code == 422


def test_unknown_routes_fail_closed(domain, identities):
    @domain.post("/new-unreviewed-operation")
    def unsafe():
        raise AssertionError("Handler must never run")
    with TestClient(domain, root_path="/domain") as client:
        assert client.post("/domain/new-unreviewed-operation", headers=bearer(identities())).status_code == 403
