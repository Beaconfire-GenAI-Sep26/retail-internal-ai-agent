# Architecture

Service boundaries, repository layout, call directions, the auth flow, and environment
variables.

## Repository structure

`auth/`, `agent/`, `domain/` and `frontend/` are the service roots. The Domain
HTTP entry point, access policy, C-01 models, migrations and seed scripts all live
in `domain/`. Shared JWT verification, HTTP handling and database configuration
live in `shared/`; shared code contains no business repositories.

Root `compose.yaml` orchestrates the services using root `.env`. `platform/`
holds gateway configuration and Postgres initialization. Cross-service tests live
in `tests/`. Backend Dockerfiles build from the root context, copy their own
service plus `shared/`, and use qualified entry points (`auth.app.main:app`,
`agent.app.main:app`, `domain.app.main:app`) to avoid colliding `app` packages.
The Agent uses `agent/pyproject.toml` and committed `agent/uv.lock`; Auth and Domain
use their own requirements files.

## Services and boundaries

| Service | Owns | Exposes | Calls | Must never |
|---|---|---|---|---|
| **gateway** (Nginx) | Routing, request IDs | Host port 18080 by default. Routes `/auth/*`, `/agent/*` and `/domain/*` with the prefix stripped, and `/*` to the frontend. | All services | Hold business logic. Route `/domain/internal/*` from the browser, so it returns 404. |
| **frontend** (React) | Analyst workspace UI | Static build | Gateway only | Call a service directly, or decide permissions itself. It hides controls, but the backend enforces. |
| **auth** (FastAPI) | Accounts, roles, store grants, refresh sessions, `auth` schema | Login, current user, refresh and logout | Postgres | Issue a token with more stores than the user's grants. |
| **agent** (FastAPI + LangGraph) | Investigations, graph checkpoints, `agent` schema | Start, status and resume of investigations | Domain, Claude API, Langfuse | Write business data, dispatch, read the `domain` schema, or store a JWT in a checkpoint |
| **domain** (FastAPI + SQLAlchemy) | All business data, `domain` schema | Cases, evidence, diagnostics, proposals, decisions, replies, rechecks, audit | Postgres | Dispatch anything that is unapproved, stale or a duplicate |
| **postgres** | Storage | Internal only | — | Let a service role reach another service's schema |

## How the services connect

```mermaid
flowchart LR
  B["Browser<br/>React workspace"] -->|"HTTPS + JWT"| G["Nginx gateway :18080"]
  G -->|"/auth"| A["Auth Service"]
  G -->|"/agent"| AG["Agent Service"]
  G -->|"/domain (public routes)"| D["Domain Service"]
  G -->|"/"| F["Frontend container"]
  AG -->|"read-only diagnostics<br/>+ proposal draft (internal)"| D
  AG -->|"model calls"| C["Claude API"]
  AG -->|"redacted traces"| L["Langfuse Cloud"]
  A --> PA[("auth schema")]
  AG --> PG[("agent schema<br/>checkpoints")]
  D --> PD[("domain schema")]
```

Calls only go in the directions shown. The Domain Service never calls the Agent Service. When the agent
needs to continue after an analyst decision or a merchant reply, the frontend calls the agent's resume
endpoint, and the agent then reads the new state from the Domain Service.

## Rules every service follows

- **Only the Domain Service changes business data or acts.** The agent's two writes go through internal routes: it creates a draft proposal and reports its investigation status. A draft does nothing until an analyst approves it.
- **Every service checks the JWT itself.** The gateway checks nothing. Auth, Agent and Domain each verify the signature, expiry, role and store grant on every request.
- **The agent forwards the user's JWT unchanged** on every Domain call, so it can never act with more rights than the analyst who started the work.
- **Internal routes need a service token.** Domain routes under `/internal/` are unreachable through the gateway. They also require the `X-Service-Token` header to match `INTERNAL_SERVICE_TOKEN`, and so does `POST /evidence/resolve`.
- **Agent calls are narrowed to one store.** `X-Store-ID` must match the resource's stored owner and be included in the JWT's grants. The Domain client permits only reads and the two internal writes; it cannot decide or dispatch proposals. The public gateway strips service tokens.
- **No tokens in checkpoints.** Graph state stores the user ID and store ID only. Every resume arrives with a fresh token on the new request.
- **Customer and merchant text is untrusted data.** `customer_comments` and merchant reply text are passed to the model as quoted evidence, never as instructions.
- **No personal data leaves the Domain Service.** Evidence carries only the synthetic `customer_ref` from `orders`, never names, phone numbers or addresses. This keeps personal data out of model calls and Langfuse traces.
- **Every log line carries the `X-Request-ID`**, plus the `case_id` and `investigation_id` where known.
- **The answer key stays hidden.** The `eval` schema holds the Golden Dataset's expected outcomes, per C-01. Only the reset script writes it, and only the B-05 evaluation runner reads it. `agent_svc` has no rights on it, and no Domain route queries it.

## Auth flow

```mermaid
sequenceDiagram
  participant UI as Frontend
  participant Auth
  participant Agent
  participant Domain
  UI->>Auth: POST /auth/login
  Auth-->>UI: JWT (user_id, role, store_ids, exp)
  Note over Auth,UI: HttpOnly refresh cookie; access token stays in memory
  UI->>Agent: POST /agent/investigations + JWT
  Agent->>Agent: verify JWT, role, store grant
  Agent->>Domain: GET diagnostics + same JWT
  Domain->>Domain: verify JWT, store grant again
  Domain-->>Agent: metrics + evidence IDs
  UI->>Auth: POST /auth/refresh + cookie (on expiry or page load)
  Auth-->>UI: Fresh JWT + current User + rotated refresh cookie
```

JWT claims, signed with HS256 and `JWT_SECRET`:

| Claim | Example | Meaning |
|---|---|---|
| `sub` | `USR-001` | User ID |
| `name` | `Ana Analyst` | Display name |
| `role` | `loe_analyst` | `viewer` or `loe_analyst` |
| `store_ids` | `["STORE-A", "STORE-B"]` | Store grants |
| `iss` | `mi-auth` | Must equal `JWT_ISSUER` |
| `iat`, `exp` | Unix seconds | Expiry is `JWT_TTL_MINUTES` after issue |

Responses: a missing, malformed or expired token gets 401. A valid token without the right role or store
gets 403.

Auth stores scrypt password hashes and SHA-256 hashes of opaque random refresh
tokens in its own schema. Refresh tokens rotate atomically; replay revokes their
family. A refresh session lasts `REFRESH_TTL_DAYS` from login, without extending
that expiry on rotation. Refresh and logout use the HttpOnly cookie independently
of access-JWT expiry. Existing access tokens expire normally after logout or a
grant change; current account grants apply to the next refresh.

## Environment variables

Compose reads the root git-ignored `.env` and supplies service-specific environment
variables. Current API settings are validated from the environment; B-02 can
extend this with its planned pydantic-settings configuration. Only `.env.example`
is committed.

| Variable | Example | Used by | Purpose |
|---|---|---|---|
| `APP_ENV` | `local` | all | `local`, `ci` or `demo` |
| `LOG_LEVEL` | `info` | all | Log verbosity |
| `APP_PORT` | `18080` | gateway | Local host port |
| `POSTGRES_DB` | `mi_agent` | postgres | Database name |
| `POSTGRES_USER`, `POSTGRES_PASSWORD` | `postgres`, `change-me` | postgres | Superuser, init only |
| `AUTH_DB_PASSWORD` | `change-me` | auth | `auth_svc` role password |
| `DOMAIN_DB_PASSWORD` | `change-me` | domain | `domain_svc` role password |
| `AGENT_DB_PASSWORD` | `change-me` | agent | `agent_svc` role password |
| `MIGRATION_DB_PASSWORD`, `EVAL_DB_PASSWORD` | empty | postgres init/admin tooling | Optional `db_migrator` and read-only `eval_runner` logins; blank disables password login |
| `JWT_SECRET` | `change-me-32-bytes-min-local-only` | auth, agent, domain | Token signing key, at least 32 bytes |
| `JWT_ISSUER` | `mi-auth` | auth, agent, domain | Expected `iss` claim |
| `JWT_TTL_MINUTES` | `60` | auth | Token lifetime |
| `REFRESH_TTL_DAYS` | `7` | auth | Absolute refresh-session lifetime |
| `COOKIE_SECURE` | `true` | auth | Secure refresh cookie; explicitly false for localhost HTTP only |
| `PUBLIC_ORIGIN` | empty | auth | Canonical browser origin for CSRF validation behind TLS/proxies; defaults to request origin |
| `SEED_AUTH_ACCOUNTS` | `false` | auth | Opt in to idempotent demo account seeding |
| `SEED_ANALYST_PASSWORD`, `SEED_VIEWER_PASSWORD` | local values | auth | Required when seeding; minimum 12 characters; existing accounts are untouched |
| `INTERNAL_SERVICE_TOKEN` | `change-me-internal` | agent, domain | Guards Domain `/internal/` routes |
| `DOMAIN_SERVICE_URL` | `http://domain:8000` | agent | Internal Domain address |
| `ANTHROPIC_API_KEY` | empty | agent | Claude API key |
| `ANTHROPIC_MODEL` | `claude-opus-5-5` | agent | Model ID, recorded in every eval run |
| `AGENT_EFFORT` | `medium` | agent | Effort for the `reason` node: `low`, `medium`, `high`, `xhigh` or `max`. `medium` is Claude Opus 5.5's default; the M0 spike measures the options. |
| `AGENT_SPEED` | `standard` | agent | `standard` or `fast`. Fast mode costs about twice as much per token. |
| `AGENT_MAX_STEPS` | `12` | agent | Maximum tool checks per investigation |
| `AGENT_MAX_RETRIES` | `2` | agent | Retries per failed model or tool call |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | empty | agent | Langfuse Cloud keys |
| `LANGFUSE_BASE_URL` | `https://cloud.langfuse.com` | agent | Langfuse v4 endpoint; legacy `LANGFUSE_HOST` is a fallback |
| `LANGFUSE_TRACING_ENABLED` | `true` | agent | Export only when enabled and both keys exist; logs remain active |
| `AGENT_RUN_TIMEOUT_SECONDS` | `1200` | agent | Wall-clock limit per investigation. A run past it fails with `RUN_TIMEOUT`. A token that expires sooner is refused at start. |
| `AGENT_MAX_QUESTIONS` | `0` | agent | Merchant questions per run. `0` until merchant questions are on, then `2`. |
| `AGENT_MAX_REASON_CALLS` | empty | agent | Optional cap on reasoning turns. Empty means `2 * AGENT_MAX_STEPS + 4`. |
| `AGENT_DOMAIN_MODE` | `http` | agent | `http` calls the Domain Service. `fixtures` answers from the agent's fixtures, for work without a Domain database. |
| `AGENT_FIXTURES_DIR` | `tests/fixtures/domain` | agent | The fixture folder for fixtures mode |
| `AGENT_CHECKPOINTER` | `memory` | agent | `memory`, or `postgres` once the `agent` schema and role exist |
| `MONITOR_GOAL_RATE` | `0.05` | domain | 7-day M&I rate goal for the demo. The proposal cites 2.25% as a real-world reference. |
| `MONITOR_SPIKE_RATIO` | `1.5` | domain | Opens a case when the 7-day rate is at least this multiple of the 28-day baseline |
| `MONITOR_MIN_ORDERS` | `100` | domain | Minimum 7-day eligible orders before a store can open a case |
| `MIN_GROUP_ORDERS` | `30` | domain | Below this, a group's rate is withheld as insufficient |
| `FRAUD_MIN_PENDING_CLAIMS` | `4` | domain | Pending claims one `customer_ref` needs in the window before `fraud_signals` flags it |
| `RECHECK_DAYS_DEFAULT` | `14` | domain | Days from dispatch to recheck when the proposal gives none |

The monitor defaults follow the C-01 report, which tunes the seed so STORE-A and STORE-B cross a 7-day
rate above 5% with at least 100 eligible orders, while STORE-I and STORE-J don't. C-02 owns the final
values. A 2.25% goal could let ordinary week-to-week noise in the normal stores, which sit near 1.5%, open cases.

A-03 adds shared JSON logging and optional Langfuse v4 hooks without changing
business DTOs, authorization or storage boundaries. Browser, gateway and backend
events share `request_id`; traced Domain calls also carry case/investigation/trace
IDs. The SDK exports only redacted telemetry projections. See
[observability](observability.md) for B-02 runner/model integration, configuration,
the read-only POC and live acceptance checks.

Compose passes each backend its own `POSTGRES_USER`, `POSTGRES_PASSWORD` and
shared host/port/database fields. The common engine factory safely constructs
the SQLAlchemy URL, including passwords with reserved URL characters. Direct
development and Domain administrative scripts may set `DATABASE_URL` instead;
it takes precedence. Domain runtime and administrative tooling use the same
factory. Migrations and evaluation seeding require an administrative identity;
runtime services stay restricted to their schemas.

The consolidated provisioning scripts live in `platform/postgres/` and retain
main's `db_migrator` / `eval_runner` separation. Domain runtime has DML rights,
while `db_migrator` owns Domain/evaluation DDL. Auth and Agent can create tables
only in their own schemas. The retired `a-01-scaffold/` layout stays deleted.
