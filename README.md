# Retail internal AI agent

DoorDash Root Cause Agent for Customer Complaint Spikes.

## Repository layout

```text
auth/          Account, JWT and refresh-session API
agent/         Investigation API and scoped Domain client; uv project
domain/        Domain API, SQLAlchemy models, migrations and seed scripts
frontend/      React analyst workspace
shared/        Common backend security, HTTP and database configuration
platform/      Nginx gateway and PostgreSQL initialization
tests/         Cross-service backend security and integration tests
compose.yaml   Integrated runtime, launched from this directory
```

Each backend is an independent process and image. Shared code contains no
business repositories. The Agent reaches Domain through HTTP; it has no access
to Domain's database schema. See [architecture](docs/architecture.md),
[contracts](docs/contracts.md), [authentication](docs/authentication.md), and
[guardrail verification](docs/guardrails.md).

For one Docker Hub repository with five service tags and an EC2 deployment,
follow the [deployment guide](docs/deployment.md). It includes PowerShell build
and transfer commands, server setup, database initialization, and release updates.

## Run locally

Requires Docker Desktop running with Linux containers on Windows or macOS, or
Docker Engine with Compose on Linux. Run commands from the directory containing
`compose.yaml`. Examples use Bash unless labeled PowerShell.

Create `.env` only if it does not already exist. Windows PowerShell:

```powershell
if (-not (Test-Path -LiteralPath .env)) {
  Copy-Item -LiteralPath .env.example -Destination .env
}
```

Bash (macOS/Linux/Git Bash):

```bash
if [ ! -f .env ]; then
  cp .env.example .env
fi
```

Set `POSTGRES_PASSWORD`, `AUTH_DB_PASSWORD`, `DOMAIN_DB_PASSWORD`,
`AGENT_DB_PASSWORD`, `JWT_SECRET` (at least 32 bytes), and
`INTERNAL_SERVICE_TOKEN` in `.env`. For an existing `.env`, add missing keys
without replacing the existing database credentials. Compose reads these values
even for `ps`, `logs` and `down`; a missing required value prevents those commands.
Validate the configuration before starting Docker services:

```bash
docker compose config --quiet
```

The localhost example enables demo accounts:
`analyst` / `Password123!` for all 15 demo stores (STORE-A through STORE-M plus
STORE-Q/R), and `viewer` / `Password123!` for STORE-A. Evaluation-only holdout
stores STORE-N/O/P are excluded. With `SEED_AUTH_ACCOUNTS=true`,
restarting Auth also reconciles the existing demo analyst's store grants while
preserving its password and sessions. Sign in again or refresh the session to get
an access token with the expanded grants.
Use `COOKIE_SECURE=true` and `PUBLIC_ORIGIN` for HTTPS deployments; the example
uses HTTP on localhost.

The Compose project name and `postgres_data` volume are preserved. Existing local
configuration is at root `.env`. For an existing database volume, apply the
idempotent service-role initialization before starting the APIs. This also
updates service-role passwords to match `.env`:

```bash
docker compose up -d --wait postgres
docker compose exec postgres sh /docker-entrypoint-initdb.d/001-service-roles.sh
docker compose up --build -d --wait
```

For a new database volume, the role initialization runs automatically:

```bash
docker compose up --build -d --wait
```

Open [the workspace](http://localhost:18080). Only the gateway publishes a host
port. API docs are at `/auth/docs`, `/agent/docs`, `/domain/docs`.

### Make commands for the demo

With GNU Make installed, run these from the repository root after configuring
`.env`. All application commands execute through Docker Compose; host Python is
not required. On Windows, use GNU Make from PowerShell, Git Bash, or WSL.

```bash
make reset   # First demo setup, or reset an existing demo and start all services
make down    # Stop the entire stack; keep database data
make up      # Build/start the entire stack; keep existing data
make status  # Show service status
make logs    # Follow logs; Ctrl+C stops following
```

`make start` and `make stop` are aliases for `up` and `down`. `make up` builds the
maintenance image, stops gateway/Agent/Domain, applies pending Domain migrations
with the administrative maintenance job, restores service grants, then starts the
full stack. Existing business data, Auth accounts/sessions, and Agent checkpoints
are preserved. `make up` creates/upgrades schema but does not seed demo data; use
`make reset` for the initial demo dataset.

This migration step also fixes existing volumes that are behind the application
code, such as a missing `cases.reopen_count` column after updating to C-05. A
healthy database connection alone does not establish that its schema is current.
If a migration fails, Make stops before restarting gateway/Agent/Domain; inspect
the error and rerun `make up` after correcting it.

**`make reset` deletes Domain business data, evaluation data, and all Agent
investigation/checkpoint history.** It preserves Auth accounts and sessions.
It builds the maintenance image, stops the gateway/Agent/Domain, clears Agent
checkpoints, reseeds the 13 demo stores, restores schema ownership and service
permissions, then starts the complete stack and waits for health checks. Refresh
the browser afterward to clear old case/investigation state from the UI.

Reset is an operator command with Docker access. The `demo-reset` service is an
explicit maintenance job using database administrator credentials from `.env`;
it is excluded from normal startup. API services keep their restricted roles.
If reseeding or permission restoration fails, the gateway/Agent/Domain are not
restarted: fix the error and rerun `make reset` before resuming the demo.
Concurrent commands from separate terminals
should be avoided while reset runs.

Compose options can be supplied without editing the Makefile, for example:

```bash
make reset COMPOSE="docker compose --env-file .env.demo -p retail-demo"
```

`make up` applies Domain migrations; `make reset` performs synthetic data seeding
as well. Manual administrative commands are in the [Domain instructions](domain/README.md). Runtime services
cannot access the evaluation schema. Investigation execution and proposal,
decision and dispatch workflows remain with their respective business tickets;
the authentication and authorization boundaries are installed now.

A-03 provides correlated JSON logs, optional redacted Langfuse tracing, and a
read-only LangGraph trace probe. See [observability](docs/observability.md) for
setup, B-02 integration hooks and the live acceptance checklist.

## Verify and develop

Run from this repository directory with Python 3.12. Use the virtual
environment's Python directly so an Anaconda or system Python on `PATH` cannot
be used accidentally.

Windows (PowerShell):

```powershell
python3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-test.txt
.\.venv\Scripts\python.exe -m pytest tests -q
```

Windows (Git Bash):

```bash
python3.12 -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements-test.txt
./.venv/Scripts/python.exe -m pytest tests -q
```

macOS/Linux (Bash):

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/python -m pytest tests -q
```

On Windows, virtual environments use `Scripts`, including when running Git
Bash. If activation fails, stop and use the explicit interpreter above.
FastAPI 0.164.0 cannot install under Python 3.9, and the Domain models require
SQLAlchemy 2.x; install the requirements into the Python 3.12 environment.

Frontend checks (Node 24):

```bash
cd frontend
npm ci
npm test
npm run lint
npm run build
cd ..
```

Use Python 3.12 and Node 24. The [Agent](agent/README.md) uses its committed uv
lockfile. The [frontend](frontend/README.md) development server proxies APIs to
the gateway; mock authentication is opt-in.

Check the running stack in Windows PowerShell. Use `curl.exe` explicitly because
Windows PowerShell aliases `curl` to `Invoke-WebRequest`:

```powershell
docker compose ps
curl.exe --fail --show-error http://localhost:18080/auth/ready
curl.exe --fail --show-error http://localhost:18080/agent/health
curl.exe --fail --show-error http://localhost:18080/domain/ready
docker compose logs --tail 50 gateway auth domain postgres
```

Bash (macOS/Linux/Git Bash):

```bash
docker compose ps
curl --fail --show-error http://localhost:18080/auth/ready
curl --fail --show-error http://localhost:18080/agent/health
curl --fail --show-error http://localhost:18080/domain/ready
docker compose logs --tail 50 gateway auth domain postgres
```

Stop the stack when finished:

```bash
docker compose down
```

Stopping preserves the database volume. Platform details and corporate CA build
instructions are in [platform/README.md](platform/README.md).

Git demo completed by Jinfan Xiang
Git demo completed by Yibin Gao
Git demo completed by Summer Li
