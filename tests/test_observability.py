import asyncio
import io
import json
import logging
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from anthropic import AsyncAnthropic
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from langgraph.graph import END, START, StateGraph

from agent.app.domain_client import DomainClient
from agent.app.trace_poc import build_graph, fixture_transport, scripted_model_transport
from agent.app.trace_poc import run as run_probe
from agent.app.tracing import Tracing
from domain.app.main import create_app as domain_app
from shared.http import install_http
from shared.observability import (JSONFormatter, REDACTED, StaticPrompt, context_scope,
                                  correlation_id, log_context, log_event, redact)


@pytest.fixture
def json_logs():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JSONFormatter())
    logger = logging.getLogger()
    logger.addHandler(handler)
    old_level = logger.level
    logger.setLevel(logging.INFO)
    yield lambda: [json.loads(line) for line in stream.getvalue().splitlines()]
    logger.removeHandler(handler)
    logger.setLevel(old_level)


@pytest.fixture
def sdk_tracing(monkeypatch):
    """Exercise the installed SDK, CallbackHandler and OTel exporter, without a network."""
    import langfuse
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    monkeypatch.delenv("SSLKEYLOGFILE", raising=False)
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-" + uuid4().hex)
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test-private")
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "true")
    exporter = InMemorySpanExporter()
    real_client = langfuse.Langfuse

    def client(**kwargs):
        return real_client(**kwargs, tracer_provider=TracerProvider(), span_exporter=exporter,
                           httpx_client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={}))))

    monkeypatch.setattr(langfuse, "Langfuse", client)
    tracing = Tracing.from_env()
    assert tracing.enabled
    yield tracing, exporter
    tracing.shutdown()


def test_redaction_withholds_prose_credentials_and_unknown_objects(monkeypatch):
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "opaque-service-secret-value")
    original = {"case_id": "CASE-0001", "nested": [{"Authorization": "Bearer private",
        "refreshToken": "private-refresh", "customer_comments": "Jane Doe at 123 Main Street",
        "text": "Contact me", "display_name": "Jane Doe", "phone": "555-123-4567"}],
        "unexpected_prose": "Jane Doe lives nearby", "unexpected_contact": "jane@example.com",
        "opaque": "opaque-service-secret-value", "input_tokens": 120, "output_tokens": 30,
        "access_tokens": ["opaque-private-access"], "refresh_tokens": ["opaque-private-refresh"],
        "date": "2026-11-19", "template": StaticPrompt("Choose a read-only check."),
        "object": SimpleNamespace(access_token="private")}
    clean = redact(original)
    encoded = json.dumps(clean)
    for private in ("Jane", "555", "jane@example.com", "opaque-service-secret-value", "private-refresh",
                    "opaque-private-access", "opaque-private-refresh"):
        assert private not in encoded
    assert clean["case_id"] == "CASE-0001"
    assert clean["input_tokens"] == 120 and clean["output_tokens"] == 30
    assert clean["date"] == "2026-11-19"
    assert clean["template"] == "Choose a read-only check."
    assert clean["object"] == REDACTED
    assert original["nested"][0]["refreshToken"] == "private-refresh"  # telemetry never mutates business data
    assert redact('{"customer_comments":"Jane Doe"}')["customer_comments"] == REDACTED
    assert redact({"request_id": "1234567890", "case_id": "CASE-00012345"}) == {
        "request_id": "1234567890", "case_id": "CASE-00012345"}


def test_logging_drops_external_messages_and_exception_text(json_logs):
    with context_scope(service="domain", request_id="browser-request", case_id="CASE-0001"):
        try:
            raise RuntimeError("Jane Doe password=unsafe jane@example.com")
        except RuntimeError:
            logging.getLogger("sqlalchemy.engine").exception("SELECT password FROM account: Jane Doe")
        log_event("http.request", status_code=503)
    lines = json_logs()
    assert lines[-1]["case_id"] == "CASE-0001"
    assert lines[-1]["request_id"] == "browser-request"
    assert lines[-2]["error_type"] == "RuntimeError"
    assert lines[-2]["event"] == "library.log"
    assert "Jane" not in json.dumps(lines)
    assert log_context() == {}


def test_http_correlation_concurrency_and_errors(json_logs):
    async def authorize(request):
        request.state.case_id = "CASE-" + request.path_params.get("case_id", "0001")
    app = FastAPI()
    install_http(app, authorize, service="domain")

    @app.get("/cases/{case_id}")
    async def case(case_id: str, request: Request):
        await asyncio.sleep(0)
        return {"request_id": log_context()["request_id"]}

    @app.get("/failure")
    def failure():
        raise RuntimeError("Jane Doe jane@example.com password=private")

    async def requests():
        async with httpx.AsyncClient(base_url="http://test", transport=httpx.ASGITransport(app=app)) as http:
            responses = await asyncio.gather(*[
                http.get(f"/cases/{number:04d}?secret=do-not-log", headers={"X-Request-ID": f"browser-{number}"})
                for number in range(1, 4)])
            assert [r.json()["request_id"] for r in responses] == [f"browser-{n}" for n in range(1, 4)]
            failed = await http.get("/failure", headers={"X-Request-ID": "failure-request"})
            assert failed.status_code == 500
            assert failed.headers["X-Request-ID"] == failed.json()["error"]["request_id"]
            invalid = await http.get("/health", headers={"X-Request-ID": "not an opaque id"})
            assert invalid.headers["X-Request-ID"] != "not an opaque id"
    asyncio.run(requests())
    lines = [line for line in json_logs() if line["event"] == "http.request"]
    assert {line["request_id"] for line in lines if line["status_code"] == 200} == {"browser-1", "browser-2", "browser-3"}
    assert all(line["service"] == "domain" and line["duration_ms"] >= 0 for line in lines)
    assert "do-not-log" not in json.dumps(json_logs()) and "Jane" not in json.dumps(json_logs())
    assert log_context() == {}
    assert correlation_id("valid_opaque-id.1") == "valid_opaque-id.1"


def test_domain_call_connects_logs_and_preserves_scope(domain_engine, settings, identities, json_logs):
    app = domain_app(domain_engine, settings, "internal-test-secret")

    async def run():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(base_url="http://domain/", transport=httpx.ASGITransport(app=app)) as http:
                domain = DomainClient(http, access_token=identities(), settings=settings, store_id="STORE-A",
                    case_id="CASE-0001", investigation_id="INV-TEST", request_id="browser-123",
                    service_token="internal-test-secret")
                with context_scope(trace_id="a" * 32):
                    assert (await domain.request("GET", "/stores/STORE-A"))["store_id"] == "STORE-A"
    asyncio.run(run())
    lines = [line for line in json_logs() if line["event"] in {"http.request", "agent.operation"}]
    assert {line["service"] for line in lines} == {"domain", "agent"}
    assert all(line["request_id"] == "browser-123" and line["case_id"] == "CASE-0001"
               and line["investigation_id"] == "INV-TEST" and line["trace_id"] == "a" * 32 for line in lines)


def test_real_graph_model_and_tools_share_sdk_trace(sdk_tracing, settings, identities, json_logs):
    tracing, exporter = sdk_tracing

    async def run():
        async with httpx.AsyncClient(base_url="http://domain/", transport=fixture_transport()) as http:
            async with AsyncAnthropic(api_key="offline", max_retries=0,
                    http_client=httpx.AsyncClient(transport=scripted_model_transport(usage={
                        "input_tokens": 40, "output_tokens": 10,
                        "cache_read_input_tokens": 5, "cache_creation_input_tokens": 20}))) as model:
                domain = DomainClient(http, access_token=identities(), settings=settings, store_id="STORE-A",
                    case_id="CASE-0001", investigation_id="INV-TEST", request_id="browser-sdk",
                    service_token="opaque-internal-secret", tracing=tracing)
                graph = build_graph(domain, model, tracing)
                return await tracing.ainvoke(graph, {"case_id": "CASE-0001", "store_id": "STORE-A",
                    "investigation_id": "INV-TEST"}, request_id="browser-sdk", case_id="CASE-0001",
                    investigation_id="INV-TEST")
    result = asyncio.run(run())
    tracing.flush()
    spans = exporter.get_finished_spans()
    assert result["status"] == "unsure"
    assert {"investigation", "load_case", "reason", "run_check", "finalize", "reason.model", "domain.claim-breakdown"} <= {s.name for s in spans}
    assert len({s.context.trace_id for s in spans}) == 1
    assert all(s.end_time >= s.start_time for s in spans)
    assert len([s for s in spans if s.parent is None]) == 1
    generation = next(s for s in spans if s.name == "reason.model")
    assert generation.attributes["langfuse.observation.type"] == "generation"
    assert json.loads(generation.attributes["langfuse.observation.usage_details"]) == {
        "input": 40, "output": 10, "cache_read_input_tokens": 5, "cache_creation_input_tokens": 20}
    assert "read-only diagnostic" in generation.attributes["langfuse.observation.input"]
    assert any(s.attributes.get("langfuse.observation.type") == "tool" for s in spans)
    root = next(s for s in spans if s.name == "investigation")
    assert "CASE-0001" in str(root.attributes) and "browser-sdk" in str(root.attributes)
    assert result["trace_id"] == format(root.context.trace_id, "032x")
    lines = [line for line in json_logs() if line["event"] == "agent.operation"]
    assert all(line["request_id"] == "browser-sdk" and line["trace_id"] == result["trace_id"] for line in lines)
    assert "opaque-internal-secret" not in str([dict(s.attributes) for s in spans])


def test_callback_errors_and_state_do_not_export_private_text(sdk_tracing):
    tracing, exporter = sdk_tracing

    async def fail(state):
        raise RuntimeError("Jane Doe lives at 123 Main Street; Bearer private-token")
    builder = StateGraph(dict)
    builder.add_node("failing_step", fail)
    builder.add_edge(START, "failing_step")
    builder.add_edge("failing_step", END)
    with pytest.raises(RuntimeError, match="Jane Doe"):
        asyncio.run(tracing.ainvoke(builder.compile(), {"customer_comments": "Jane Doe", "token": "private-token"},
            request_id="failed-sdk", case_id="CASE-0001", investigation_id="INV-ERROR"))
    tracing.flush()
    spans = exporter.get_finished_spans()
    assert any(s.attributes.get("langfuse.observation.level") == "ERROR" for s in spans)
    exported = str([(dict(s.attributes), s.events, s.status) for s in spans])
    assert "Jane Doe" not in exported and "private-token" not in exported and "123 Main" not in exported
    assert "RuntimeError" in exported
    assert log_context() == {}


def test_concurrent_runs_and_resume_get_isolated_traces(sdk_tracing):
    tracing, exporter = sdk_tracing
    builder = StateGraph(dict)
    async def step(state):
        await asyncio.sleep(0)
        return {"status": "unsure"}
    builder.add_node("step", step)
    builder.add_edge(START, "step")
    builder.add_edge("step", END)
    graph = builder.compile()

    async def run():
        await asyncio.gather(*[tracing.ainvoke(graph, {}, request_id=request_id, case_id=case_id,
            investigation_id=investigation_id) for request_id, case_id, investigation_id in
            (("start-1", "CASE-0001", "INV-ONE"), ("resume-1", "CASE-0001", "INV-ONE"),
             ("start-2", "CASE-0002", "INV-TWO"))])
    asyncio.run(run())
    tracing.flush()
    roots = [span for span in exporter.get_finished_spans() if span.name == "investigation"]
    assert len(roots) == 3 and len({span.context.trace_id for span in roots}) == 3
    assert all(span.parent is None for span in roots)
    sessions = [span.attributes.get("session.id") for span in roots]
    assert sessions.count("INV-ONE") == 2 and sessions.count("INV-TWO") == 1
    assert log_context() == {}


def test_probe_offline_success_failure_and_missing_live_configuration(monkeypatch, json_logs):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    args = SimpleNamespace(offline=True, domain="fixtures", case_id="CASE-0001", store_id="STORE-A",
                           inject_tool_error=False)
    assert asyncio.run(run_probe(args)) == 0
    final = next(line for line in json_logs() if line["event"] == "poc.finished")
    assert final["offline"] and not final["ingestion_verified"]
    assert final["request_id"] and final["investigation_id"].startswith("INV-")
    assert len(final["investigation_id"]) == 30  # INV- plus 26-character ULID
    args.inject_tool_error = True
    assert asyncio.run(run_probe(args)) == 1
    failures = [line for line in json_logs() if line["event"] == "agent.operation_failed"]
    assert any(line.get("error_code") == "UPSTREAM_UNAVAILABLE" and line["status_code"] == 503 for line in failures)
    args.offline = False
    assert asyncio.run(run_probe(args)) == 2


def test_no_keys_and_exporter_failure_do_not_break_workflow(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    assert not Tracing.from_env().enabled
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "public-only")
    assert not Tracing.from_env().enabled

    class BrokenClient:
        def start_as_current_observation(self, **kwargs):
            raise RuntimeError("secret exporter error")
        def get_current_trace_id(self):
            raise RuntimeError()
        def flush(self):
            raise RuntimeError()
        def shutdown(self):
            raise RuntimeError()
    tracing = Tracing(BrokenClient())
    graph = SimpleNamespace(ainvoke=None)
    async def invoke(state, config):
        return {"status": "unsure"}
    graph.ainvoke = invoke
    assert asyncio.run(tracing.ainvoke(graph, {}, request_id="offline", case_id="CASE-0001",
                                       investigation_id="INV-OFFLINE"))["status"] == "unsure"
    tracing.shutdown()


def test_agent_lifespan_flushes_injected_tracing(settings):
    from agent.app.main import create_app
    called = []
    tracing = SimpleNamespace(shutdown=lambda: called.append("shutdown"))
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    with TestClient(create_app(settings, http, service_token="test-secret", tracing=tracing), root_path="/agent") as client:
        assert client.get("/agent/health").status_code == 200
    assert called == ["shutdown"]
    asyncio.run(http.aclose())
