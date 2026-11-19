# Langfuse and application logs (A-03)

The Agent exports one Langfuse trace per start/resume **segment**. Segments share
the investigation ID as their Langfuse session. Trace metadata contains
`case_id`, `investigation_id` and the initiating `request_id`. Graph callbacks
record node timing and nesting; direct Anthropic calls use a generation
observation; the scoped Domain client records tool inputs, results and errors.
Model usage includes input/output tokens and cache counters when returned.
Langfuse can calculate cost for a model in its pricing catalog; no cost is
invented for unknown models or scripted calls.

## Configuration

Add these server-side settings to root `.env` (never frontend `VITE_*` settings):

```dotenv
APP_ENV=local
LOG_LEVEL=info
LANGFUSE_BASE_URL=https://cloud.langfuse.com
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_TRACING_ENABLED=true
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-opus-5-5
```

Use the endpoint for your Langfuse region/project. `LANGFUSE_HOST` is accepted as
a migration fallback; `LANGFUSE_BASE_URL` takes precedence. Missing/partial keys
or `LANGFUSE_TRACING_ENABLED=false` disable export. Exporter failures log a safe
warning and do not change business results. The Agent flushes and shuts down the
SDK in its lifespan cleanup, off the event loop. Backend logs remain enabled
without Langfuse. Package versions and the agent lockfile pin the tested v4 API,
including the callback's error-description override.

## Correlation

| Hop | Behavior |
| --- | --- |
| Browser | Axios assigns an opaque `X-Request-ID`, keeps it on a 401 retry, and records a JSON console event with status, duration and known case/investigation IDs. A refresh is a separate HTTP request with its own ID. |
| Gateway | Validates or creates the request ID, forwards it, and echoes it on every response. JSON access logs include case/investigation IDs, service route, status and upstream timing. |
| Auth/Agent/Domain | Shared HTTP middleware echoes the same ID and logs successes, validation/auth failures, upstream failures and unexpected exceptions. Async task context isolates simultaneous requests. |
| Agent → Domain | The scoped client forwards the original JWT unchanged and includes `X-Request-ID`, `X-Case-ID`, `X-Investigation-ID` and the active `X-Trace-ID`. Domain logs carry these fields. |
| Langfuse | Root trace metadata and the `investigation.started` application event connect the request/case/investigation IDs to the actual SDK trace ID. |

Correlation headers grant no access. Domain still resolves resource ownership
and enforces signed store grants and service credentials. The public gateway
strips `X-Service-Token` and `X-Trace-ID`, and validates correlation IDs. Request
IDs accept only `[A-Za-z0-9._-]{1,128}` in both gateway and services. Use random
opaque values, never personal data. Startup/lifecycle logs have null request IDs.

To investigate a browser failure, copy its Network response `X-Request-ID` or
console event. Search container logs for that ID:

```powershell
docker compose logs --no-log-prefix gateway auth agent domain frontend |
  Select-String 'YOUR-REQUEST-ID'
```

Use the case or investigation ID to find later polls/resume segments with new
request IDs. Search Langfuse trace metadata for those same IDs.

## Privacy boundary

`shared/observability.py` creates a telemetry projection without mutating Domain
responses, model responses or graph state. Both explicit observations and the
Langfuse callback's SDK mask apply it. Credentials, cookies, passwords, names,
email/phone/address fields, customer comments, merchant replies and narrative
fields are withheld. Unknown strings containing whitespace are withheld too;
regex filters additionally scrub email/phone patterns, bearer/JWT/API keys and
configured opaque secrets. Unknown Python objects are never serialized with
`repr`. Numeric metrics, evidence IDs, enums and usage counters remain visible.

Model message content is withheld entirely. To review prompts, trace their
structure, a template ID and static prompt text, with redacted structured evidence
on the surrounding graph/tool observation. `StaticPrompt` explicitly marks
source-controlled text; **never wrap user input, rendered evidence, model output
or merchant/customer prose in it**. The POC records its full static prompt this
way. Text withholding means traces intentionally cannot reconstruct raw evidence
or a full transcript; authorized analysts use Domain for that.

Business exception messages/stacks are withheld, since they can contain SQL
parameters, private text or credentials. Errors retain their type, safe Domain
error code/status and latency. The Langfuse graph callback overrides its raw
error-description behavior. Direct observation contexts close without passing
business exceptions to OpenTelemetry, preventing automatic exception events from
bypassing the mask. Application logs use fixed event names and allowlisted
fields; third-party log prose becomes `library.log` with its logger/severity/type.
Uvicorn access logging is disabled. Nginx access events omit client IPs, URL
queries, arbitrary paths and all headers/bodies; normal Nginx error prose is
suppressed in favor of access status/timing events (critical engine failures can
still reach stderr). Do not enable raw SDK/HTTP/SQL debug logging or another
unfiltered OpenTelemetry/LangSmith exporter.

## Hooks for the B-02 workflow

`app.state.tracing` is initialized by the Agent lifespan. Capture only correlation
IDs when scheduling a background task, and wrap **each** run/resume with:

```python
result = await app.state.tracing.ainvoke(
    graph, initial_state_or_resume_command,
    request_id=request_id, case_id=case_id, investigation_id=investigation_id,
    config={"configurable": {"thread_id": investigation_id}},
    context=runtime_context,  # fresh JWT/scoped clients here, never in state/config
)
```

This adds a fresh redacting Langfuse callback without replacing existing
callbacks. B-02's start handler must pass `tracing=app.state.tracing` when binding
its new `DomainClient`; the existing resume authorization path already does so.
Use `tracing.model_call(client, prompt_template=StaticPrompt(STATIC_TEMPLATE),
...)` for `messages.create`. For B-02's streaming adapter, wrap the streaming
call and final-message read in `tracing.observation("reason.model",
as_type="generation", model=..., input=...)`, then update the observation with
the final model, redacted output and `usage_details={"input": ..., "output": ...}`
plus cache counters. Record every retry as a separate generation. The callback
cannot see calls made directly through the Anthropic SDK.

Guard/gate rejections can use `tracing.observation("guard.rejected", ...)` with
rule IDs and counters, keeping narrative feedback private. The wrapper does not
persist credentials, add business endpoints, decide proposals or dispatch.

## POC and acceptance verification

This checkout currently has A-01/A-02's scaffold; B-02 investigation handlers,
the production graph and C-02 case/diagnostic routes are still pending. The
read-only A-03 probe supplies a runnable **real LangGraph** with `load_case →
reason → run_check → finalize`. A model chooses an allowlisted diagnostic;
execution uses the existing scoped Domain client. It finishes `unsure`, because
one check cannot satisfy the production conclude gate. It writes no business
data, proposals or checkpoints. Fixture data is synthetic probe data, independent
of the hidden evaluation schema.

From the repository root:

```powershell
uv sync --locked --project agent
# No credentials, network calls or Langfuse export; zero scripted usage counters.
uv run --project agent python -m agent.app.trace_poc --offline

# Actual Claude call + Langfuse export, with synthetic Domain tool responses.
uv run --project agent --env-file .env python -m agent.app.trace_poc

# Exercise a failed diagnostic; expected nonzero exit and ERROR observations.
uv run --project agent --env-file .env python -m agent.app.trace_poc --inject-tool-error
```

For real Domain calls after C-02 is runnable, set a fresh analyst JWT in
`POC_ACCESS_TOKEN` and a reachable `DOMAIN_SERVICE_URL` in `.env`, then append
`--domain http --case-id CASE-0001 --store-id STORE-A`. Through the local gateway,
use `DOMAIN_SERVICE_URL=http://localhost:18080/domain`; inside Compose use
`http://domain:8000`. `--offline` always requires fixtures.

The live success command requires both Langfuse keys and the Anthropic key,
authenticates to Langfuse, exports/flushes, then polls the read API for up to
30 seconds. It exits zero only after reading back the graph nodes, a generation
and a tool observation. `poc.finished` prints the trace URL, IDs and
`ingestion_verified=true`. Exit 2 means missing/disabled configuration; exit 1
means a failed run or unconfirmed ingestion. A trace URL by itself proves no
ingestion. For an injected failure, use the IDs in `investigation.started` to
inspect the failed trace. Offline output explicitly says `offline=true` and
`ingestion_verified=false` and is not evidence of cloud acceptance.

Before closing A-03, retain a live trace URL and a matching JSON log sample;
confirm node nesting/timing, prompt template, model, usage, tool arguments/results,
safe errors where applicable, and the shared case/request IDs. Once B-02 lands,
repeat on its production graph using the hooks above.

Automated checks use the **installed Langfuse SDK, graph callback, LangGraph,
Anthropic SDK and an in-memory OpenTelemetry exporter** to inspect parentage,
usage, safe error descriptions, privacy and matching logs without external keys.
Cross-service tests exercise real ASGI transport and scope verification.

```powershell
python3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-test.txt
.\.venv\Scripts\python.exe -m pytest tests -q
npm --prefix frontend test
npm --prefix frontend run lint
npm --prefix frontend run build
docker compose config --quiet
```

Automated verification does not substitute for live Langfuse ingestion. If your
Windows sandbox prevents asyncio's local socket pair, run the checks with local
loopback access. Keep any corporate CA configuration; never disable TLS checks.
