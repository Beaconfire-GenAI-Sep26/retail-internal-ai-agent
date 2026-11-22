# Agent Service

The FastAPI entry point is `agent.app.main:app`. It runs B-02's investigation API,
LangGraph, bounded runner and checkpoints (in memory by default) behind A-02's shared JWT
boundary. The typed HTTP tools use the request-scoped Domain capability. No JWT
or Domain client belongs in checkpoint state. Merchant questions pause a run until
`POST /investigations/{id}/resume`; they are off while `AGENT_MAX_QUESTIONS=0`, and
a Domain without the merchant-replies route (C-05) gets none. With C-05's mock merchant,
a question on STORE-A, B, L or M is answered when it's approved, so the resume after the
decision carries the run on without stopping at `awaiting_merchant` (a second question
pauses it again); STORE-K never answers, and the analyst records `no_reply`.
The CLI never asks, and fixtures mode never offers questions. With
`AGENT_CHECKPOINTER=postgres` (the Compose default), a paused run survives a
restart. The live restart test runs with `AGENT_IT_DATABASE_URL` set to a test
database it may empty: `uv run --project agent pytest agent/tests/live/test_live_postgres.py`.

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

## Commands

Run these from the repository root unless the row says `agent/`.

| What | Command |
|---|---|
| Tests (no network, no API key), from `agent/` | `uv run pytest` |
| Tests against a running Domain, from `agent/` | `AGENT_IT_DOMAIN_URL=… AGENT_IT_JWT_SECRET=… uv run pytest -m live_domain` (see below) |
| The API, answering Domain calls from fixtures | `AGENT_DOMAIN_MODE=fixtures uv run --project agent uvicorn agent.app.main:app --reload` |
| One investigation in the terminal, real Claude calls | `uv run --project agent python -m agent.app.cli --store STORE-A` |
| The same, with scripted turns and no API key | `uv run --project agent python -m agent.app.cli --store STORE-A --dry-run` |
| One investigation against the real Domain | `uv run --project agent python -m agent.app.cli --domain http --case CASE-0001 --token <jwt> [--dry-run]` |
| M0 spike, offline checks only | `uv run --project agent python -m agent.scripts.m0_spike` |
| M0 spike, plus 8 real calls (about $1) | `uv run --project agent python -m agent.scripts.m0_spike --yes` |
| Rebuild the Domain fixtures | `uv run --project agent python agent/scripts/make_fixtures.py` |
| Golden Dataset evaluation (B-05), Compose stack running | `uv run --project agent python -m agent.scripts.golden_eval --reps 3 --final` (see below) |
| Image | `docker build -f agent/Dockerfile .` |

The CLI and the spike write their reports to `agent/scripts/out/`, which is git-ignored. Settings come from
`agent/.env`; from the repository root, a root `.env` overrides it.

## Fixtures mode

With `AGENT_DOMAIN_MODE=fixtures`, Domain calls are answered from `tests/fixtures/domain/` for CASE-0001
(STORE-A, POS modifier), CASE-0002 (STORE-B, dinner packing) and CASE-0003 (STORE-C, a flat store). A query
with no matching fixture returns `data_sufficient: false` with a "no fixture" note, and the CLI counts these
misses. `scripts/make_fixtures.py` builds the fixtures from a simulation of the C-01 scenarios. The numbers
are synthetic, close to the seeded database but not equal to it. The action catalog comes from
`app/data/catalog.json`, the same copy the agent uses when Domain has no catalog route.

## Run against the real Domain

The agent calls Domain directly, never through the gateway: the gateway strips `X-Service-Token` and blocks
`/domain/internal`. Every call forwards the analyst's JWT, so the agent sees exactly what that user can see.
Once the case's store is known, the scoped client adds `X-Store-ID` and `X-Investigation-ID`, and it adds
`X-Service-Token` only on the two `/internal/` writes and on `POST /evidence/resolve`.

1. Start Domain with its database: the root compose's `postgres`, migrated and seeded as
   [domain/README.md](../domain/README.md) describes. From the repository root, run
   `python -m uvicorn domain.app.main:app --port 8010` as `domain_svc`, with `JWT_SECRET` (at least 32 bytes),
   `JWT_ISSUER`, `INTERNAL_SERVICE_TOKEN` and a database URL. Point the database URL at `127.0.0.1`, not
   `localhost`: on Windows, `localhost` can try IPv6 first and stall every new connection.
2. Open the cases: from the repository root, get a token with `python -m domain.scripts.make_demo_token`, then
   `POST /monitor/run` with `{"as_of": "2026-11-15"}` and an `Idempotency-Key` header. That opens five cases,
   CASE-0001 to CASE-0005, for STORE-A, B, K, L and M.
3. In `agent/.env`, set `AGENT_DOMAIN_MODE=http`, `DOMAIN_SERVICE_URL` to Domain's address (for example
   `http://127.0.0.1:8010`), and the same `JWT_SECRET`, `JWT_ISSUER` and `INTERNAL_SERVICE_TOKEN` as Domain.
4. Run one investigation with the CLI (`--domain http --case CASE-0001 --token <jwt>`), or start the API
   (`uv run --project agent uvicorn agent.app.main:app --port 8011`) and `POST /investigations`. The CLI accepts
   only an analyst's token, as the API does, and takes the store from the case.

While Domain has no catalog, proposals or status route, the agent uses the bundled catalog, finishes a
diagnosis without saving a proposal and skips the status report. Once Domain has its `/internal/` routes,
every run over HTTP, `--dry-run` included, saves a real pending proposal and reports its status. While a case
has a pending proposal, `POST /investigations` refuses a new run with 409 `PROPOSAL_PENDING`
(`details.proposal_id`) and the CLI stops before it starts, so decide or reject the proposal first, or reseed
Domain. The API also starts a fresh run only on an `open` case, or an `investigating` one with no active run
(409 `CASE_NOT_STARTABLE`), so a decided case needs a reseed. The CLI skips that rule, so you can rerun a case.
The live suite rejects the proposals it saves and returns STORE-A's case to `open` before its API test.

The live suite runs the tools, the evidence check, the scripted STORE-A and STORE-B investigations and the API
against that Domain. It skips unless both variables are set. From `agent/`:

```bash
AGENT_IT_DOMAIN_URL=http://127.0.0.1:8010 AGENT_IT_JWT_SECRET=<Domain's JWT_SECRET> uv run pytest -m live_domain
```

`AGENT_IT_SERVICE_TOKEN` defaults to `INTERNAL_SERVICE_TOKEN`. The suite mints its own test tokens and runs the
monitor itself, acting as Auth and the frontend.

## Golden Dataset evaluation (B-05)

`agent/scripts/golden_eval.py` runs the agent and a fixed-rule baseline on the seeded scenarios and grades both
with the same code checks ([agent-graph.md](../docs/agent-graph.md#evaluation)). It drives the running Compose
stack through the gateway, so set `AGENT_EFFORT=medium` in the root `.env` first. Each round reseeds Domain and
clears the agent's runs, which wipes Domain's data.

- `--reps 3 --final` is the full run: three rounds of the agent on the dev scenarios (the baseline runs once; it's
  deterministic), then the STORE-B recheck and reopen chain and the permission probes. A dev run took about 30
  minutes and $4.50 at medium effort.
- `--self-check` grades the answer key and an empty answer through the same grader, with no Claude call.
- `--cases GS-02 --reps 1 --variant v2` reruns chosen scenarios into a new folder, for example after a fix.
- `--split holdout` runs the holdout scenarios into `agent/scripts/out/golden-holdout/`, so they never pool with
  dev. The runner reseeds with `--holdout` every round, which needs C-04's `domain/scripts/holdout_stores.py`: add
  it and rebuild the Domain image first.

Results go to `agent/scripts/out/golden/`. `baseline/` and `v1/` each hold `results.jsonl`, `traces/`, `run.json`
(one header per session: git SHA, seed, label hash, agent settings) and, only when a run can't be scored,
`errors.jsonl`. `--final` adds `chain.json` and `probes.json` to the agent's folder. `summary.md` holds the baseline
and the variant from the latest run. The HTML report is built from the same folder by the claude-api skill's report
builder (`build-report-lite.mjs`), so rerun the builder after the command. Each result's `langfuse_session` is the
investigation ID, which is the run's Langfuse session.

## Layout

| Path | What it holds |
|---|---|
| `app/main.py`, `app/api/` | FastAPI app behind the shared JWT boundary, `/health`, `/ready` and the investigation routes |
| `app/auth.py` | The JWT check, through `shared/security.py`: HS256, issuer, role, store grants |
| `app/runner.py`, `app/store.py` | Background runs and the in-memory investigation index |
| `app/graph/` | State, wiring, nodes, and the pure guard, gate, finalize and policy rules |
| `app/prompts/` | The system prompt and the per-turn renderer |
| `app/llm/` | The output schema, the Claude adapter and the scripted test model |
| `app/tools/registry.py` | The seven model tools: prompt text, request conversion, canonical keys |
| `app/domain/` | The Domain interface, the HTTP client, the fixture client and the bundled catalog loader |
| `app/domain_client.py` | The scoped Domain capability: allowed paths and methods, the case and store pin, the headers |
| `app/data/catalog.json` | The bundled action catalog |
| `app/contracts/` | Pydantic mirrors of the contracts |
| `tests/` | Unit, graph and API tests, prompt snapshots, the Domain fixtures, and `tests/live/` against a running Domain |

Prompt snapshots live in `tests/unit/snapshots/`. After an intended prompt change, refresh them from `agent/` with
`UPDATE_SNAPSHOTS=1 uv run pytest tests/unit/test_render.py` and review the diff.
