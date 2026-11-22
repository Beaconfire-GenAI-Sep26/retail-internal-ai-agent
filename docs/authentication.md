# A-02 authentication and access control

The runtime is the root `compose.yaml`, which builds `auth/`, `agent/`, `domain/`
and the analyst workspace in `frontend/`. Gateway and database initialization
live in `platform/`; common backend utilities live in `shared/`.
Auth, Agent and Domain share JWT validation code, but no repositories or business
data. Each independently checks HS256, issuer, required claims, expiry, role and
store grants. `JWT_SECRET` must contain at least 32 bytes.

## Accounts and sessions

Copy the root `.env.example` into your local `.env`, preserving any existing
database configuration. Replace its secret/password placeholders before running
`docker compose up --build` from the repository root. Required settings are listed
in the example. Never commit `.env`.

With `SEED_AUTH_ACCOUNTS=true`, Auth inserts these accounts if they do not exist:

| Username | User ID | Role | Store grants |
|---|---|---|---|
| `analyst` | `USR-001` | `loe_analyst` | All 15 demo stores: STORE-A through STORE-M plus STORE-Q/R; holdout STORE-N/O/P excluded |
| `viewer` | `USR-002` | `viewer` | STORE-A |

Passwords come from `SEED_ANALYST_PASSWORD` and `SEED_VIEWER_PASSWORD` (minimum
12 characters). The localhost example uses `Password123!` for both; seeding is
disabled by default unless explicitly enabled. Seeding reconciles the known demo
analyst (`USR-001`, username `analyst`, role `loe_analyst`) to demo-only store
grants on existing volumes, removing any previously granted holdout stores.
Passwords, sessions, profile fields, active
state, and role changes are preserved; Viewer and other accounts are unchanged.
Auth uses explicit signed grants and does not read Domain or evaluation tables.
Sign in again or refresh the session to obtain the expanded JWT claims. Existing
access tokens retain their old grants until refreshed or expired. C-01 still
owns seeding the synthetic stores and orders.

`POST /auth/login` returns the contract's `LoginResponse` and a random refresh
credential in a host-only HttpOnly cookie. Only its hash is stored. Access tokens
stay in Redux memory. Page loads and expired requests call `/auth/refresh`, which
atomically consumes the old cookie and issues a replacement plus a JWT with the
account's current grants. Rotated-token replay revokes the entire session family.
The absolute refresh expiry does not slide. `/auth/logout` revokes that family
and clears the cookie, including when the access token is expired.

The frontend shares refresh calls across bootstrap and concurrent 401s, retries
each request once, and ignores late refresh/bootstrap results after logout.
Login failures and 403s never trigger refresh. Auth returns `no-store` and the
shared error envelope. Missing/invalid/expired JWTs return 401 with
`WWW-Authenticate: Bearer`. Invalid role or store access returns 403. Other-store
case/proposal/evidence reads return 404 according to the contract.

Cookies use `SameSite=Lax`, `Path=/auth`, and `Secure` by default. Only the
localhost HTTP example sets `COOKIE_SECURE=false`. For HTTPS deployments, set it
to true and set `PUBLIC_ORIGIN` to the browser-facing origin. Cookie-authenticated
mutations reject cross-site Origin and Fetch Metadata headers. Local Vite uses
same-origin proxies for `/auth`, `/agent`, `/domain`; keep `VITE_API_URL` empty.

Access JWTs are stateless: logout, account disablement and grant changes affect
refresh immediately, while already-issued JWTs last until their configured expiry.
Agent background work never refreshes credentials itself. Resume requests carry
a fresh user JWT; tokens and Domain clients must never enter checkpoints or traces.

## Service boundaries and existing databases

On a **new** Postgres volume, `platform/postgres/001-service-roles.sh` creates `auth_svc`,
`domain_svc` and `agent_svc`, each with only its own schema. Auth creates its two
tables on startup. Domain migrations/evaluation seeding remain a separate admin
operation because runtime services must not read or modify the `eval` schema.

Postgres init scripts do not run again on existing volumes. After updating your
local `.env`, apply the idempotent role/schema script explicitly from the
repository root before starting the application services:

```bash
docker compose up -d --wait postgres
docker compose exec postgres sh /docker-entrypoint-initdb.d/001-service-roles.sh
docker compose up --build -d --wait
```

The script sets service-role passwords from `.env` and restores schema grants
without dropping schemas or data. The existing administrator password must still
match the database; changing `POSTGRES_PASSWORD` in `.env` alone does not change
the stored administrator password. Do not delete the volume to apply this change.

After an admin-run C-01 migration/reset recreates `domain`, restore runtime grants
as that migration owner (these statements grant nothing on `eval`):

```sql
GRANT USAGE, CREATE ON SCHEMA domain TO domain_svc;
GRANT ALL ON ALL TABLES IN SCHEMA domain TO domain_svc;
GRANT ALL ON ALL SEQUENCES IN SCHEMA domain TO domain_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA domain GRANT ALL ON TABLES TO domain_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA domain GRANT ALL ON SEQUENCES TO domain_svc;
```

The gateway blocks `/domain/internal` and its children and strips public
`X-Service-Token` headers. Internal Domain writes require the original user JWT,
LOE Analyst role, service token, investigation ID and matching store context.
The service token alone never authenticates a user.

## Integration points for the business tickets

The checkout had only health handlers in Agent/Domain at the start of A-02.
A-02 supplies store/menu reads against C-01 data and a default-deny access policy
covering B-01's route contract. It does not implement B-02 investigation execution
or C-02/C-03 case, proposal, decision, dispatch, audit and recheck workflows.
Those routes remain absent until their owning tickets add them. The security
tests use probe handlers to verify authorization before a business side effect.

- Add business handlers to the existing `create_app` apps so their security
  boundary remains installed. An unknown operation is denied until added to the
  access policy.
- Domain single-resource checks resolve ownership in storage: proposals and
  rechecks join their `case_id` to `domain.cases`. Never trust a body/header store
  to assign proposal ownership. C-03 must authorize before deciding/dispatching,
  then enforce pending status, version and idempotency in its transaction.
- List/monitor handlers must scope SQL with `request.state.store_ids`, including
  empty grants. `scoped_case_query` provides the case-list query; C-02 supplies
  complete `CaseSummary` serialization. Do not serialize the hidden `eval` tables.
- B-02 passes `investigation_lookup(id)` to Agent's `create_app`, returning the
  checkpoint's `{case_id, store_id}`. Missing ownership fails closed. Agent checks
  it against a Domain case read on each start/status/resume.
- Resume handlers receive `request.state.domain_client`, bound to that case,
  store, investigation and request. Start handlers create `DomainClient` after
  generating the investigation ID, using `request.state.access_token` and the
  verified `request.state.case_id`/`store_id`.
- Use `DomainClient.request` for all tools. It forwards the JWT unchanged, limits
  paths and methods, rejects another case/store even if the user has that grant,
  forbids decisions/dispatch, and supplies service credentials only for the two
  internal writes and evidence resolution. Domain rechecks ownership and scope.

## Verification

From the repository root with Python 3.12 and Node 24, follow the
[platform-specific setup and test commands](../README.md#verify-and-develop).
For macOS/Linux in Bash:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/python -m pytest tests -q
cd frontend
npm ci
npm test
npm run lint
npm run build
cd ..
```

Backend coverage includes invalid/expired/tampered JWTs on all three services,
role and store denial, scoped lists, proposal ownership, internal credentials,
real in-process Agent-to-Domain calls, refresh rotation/replay/expiry, logout,
grant changes and persistence across service restart. Frontend coverage includes
simultaneous expiry, delayed 401s, failed refresh, bounded retry, bootstrap sharing
and refresh/bootstrap results racing logout.
