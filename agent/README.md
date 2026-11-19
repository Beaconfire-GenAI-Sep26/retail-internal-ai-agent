# Agent Service

The FastAPI entry point is `agent.app.main:app`. Owns investigation execution and
checkpoints in the planned architecture. Current code supplies the authentication
boundary and the request-scoped Domain client; workflow handlers are added by
B-02/B-03/B-04. No user JWT or Domain client belongs in checkpoint state.

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
