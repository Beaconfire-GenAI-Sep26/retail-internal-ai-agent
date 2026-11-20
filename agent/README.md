# Agent Service

The FastAPI entry point is `agent.app.main:app`. It runs B-02's investigation API,
LangGraph, bounded runner and in-memory checkpoints behind A-02's shared JWT
boundary. The typed HTTP tools use the request-scoped Domain capability. No JWT
or Domain client belongs in checkpoint state. Resume/merchant interactions and
Postgres persistence remain later workflow milestones.

Use `AGENT_DOMAIN_MODE=fixtures` for the seeded graph fixtures, or `http` for the
Domain service. Without an Anthropic key, liveness stays healthy and readiness
and investigation starts report that model configuration is missing. Tests use
the scripted model; no external model call is needed to validate the graph.

Dependencies use `pyproject.toml` and the committed `uv.lock`. From the repository
root:

```bash
uv sync --locked --project agent
uv run --project agent --env-file .env uvicorn agent.app.main:app --root-path /agent --reload
```

For direct development, configure `DOMAIN_SERVICE_URL` to a reachable Domain API;
the default `http://domain:8000` is the Docker-network address. Ensure JWT/service
credentials match Domain. Compose configures these automatically:

```bash
docker compose up --build agent
```

The Docker build uses the root context and `uv sync --frozen --no-dev`, copying
only this service and `shared/`. After dependency changes, run
`uv lock --project agent` and commit both dependency files.

The Agent calls Domain over HTTP with the original user JWT plus a narrowed
case/store context. Its client cannot approve or dispatch proposals. See
[authentication integration](../docs/authentication.md#integration-points-for-the-business-tickets)
and the [workflow plan](../docs/agent-implementation-plan.md).

A-03 initializes optional Langfuse v4 tracing as `app.state.tracing`, instruments
the scoped Domain client and emits correlated JSON logs. The B-02 runner and
Claude adapter use the hooks in [observability](../docs/observability.md). Run the
read-only graph probe from the repository root without credentials:

```powershell
uv run --project agent python -m agent.app.trace_poc --offline
```

For a real Claude/Langfuse run, set the keys in root `.env` and replace `--offline`
with `--env-file .env` **before** `python`. The guide covers live trace readback,
synthetic versus real Domain tools, redaction and the remaining B-02 dependency.
