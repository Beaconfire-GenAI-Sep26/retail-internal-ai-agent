# Planned A01 Service and Gateway Scaffold

This folder holds the draft scaffold for later implementation of Jira task
SCRUM-13. Review the service names and environment contract with B-01 before
integrating the scaffold into the application. Keep this folder together so its
relative Docker build paths continue to work.

The A-01 scaffold runs three independently built FastAPI services, a React and
React Router frontend served by Nginx, an Nginx API gateway, and PostgreSQL.

## Run when implementation begins

Start Docker Desktop with Linux containers enabled. From the repository root,
change into the scaffold folder.

```powershell
Set-Location a-01-scaffold
```

Create your local configuration if `.env` does not already exist.

```powershell
Copy-Item .env.example .env
```

Set all six passwords in `.env` to distinct local values, then run

```powershell
docker compose up --build
```

Open <http://localhost:18080>. The page checks Auth, Agent, and Domain through the
gateway. Domain readiness also verifies a real PostgreSQL connection. To run in
the background and wait for container health, use

```powershell
docker compose up --build -d --wait
```

## Verify A-01

```powershell
docker compose ps
Invoke-RestMethod http://localhost:18080/health
Invoke-RestMethod http://localhost:18080/auth/health
Invoke-RestMethod http://localhost:18080/agent/health
Invoke-RestMethod http://localhost:18080/domain/health
Invoke-RestMethod http://localhost:18080/domain/ready
```

All six long-running containers should become healthy, and the one-time
`db-setup` container should exit with code 0. Every endpoint should return
`status: ok`, and `/domain/ready` should also return `database: ok`.
Open the frontend and confirm all three entries show Ready.

API documentation is available at `/auth/docs`, `/agent/docs`, and `/domain/docs`.
Each documentation page uses its gateway prefix to retrieve its OpenAPI schema.

## Service and environment contract for B-01

| Folder | Compose service | Container address | Gateway prefix |
| --- | --- | --- | --- |
| `services/auth` | `auth` | `http://auth:8000` | `/auth` |
| `services/agent` | `agent` | `http://agent:8000` | `/agent` |
| `services/domain` | `domain` | `http://domain:8000` | `/domain` |
| `frontend` | `frontend` | `http://frontend:80` | `/` |
| `gateway` | `gateway` | `http://gateway:80` | Host port 18080 |
| PostgreSQL image | `postgres` | `postgres:5432` | Internal network |

The gateway removes `/auth`, `/agent`, or `/domain` before forwarding a request.
FastAPI receives `ROOT_PATH` at runtime so its documentation uses the public
prefix. New business endpoints belong inside the respective service and use
paths relative to that prefix. Frontend calls use relative URLs on the gateway
origin. Server-to-server calls use Compose service names.

| Variable | Consumer | Purpose |
| --- | --- | --- |
| `APP_PORT` | Gateway port mapping | Host port, default 18080 |
| `POSTGRES_DB` | PostgreSQL, setup, service URLs | Database name |
| `POSTGRES_USER`, `POSTGRES_PASSWORD` | PostgreSQL and setup | Database administrator, used for initialization and provisioning |
| `AUTH_DB_PASSWORD` | Setup and Auth | Password for `auth_svc` |
| `AGENT_DB_PASSWORD` | Setup and Agent | Password for `agent_svc` |
| `DOMAIN_DB_PASSWORD` | Setup and Domain | Password for `domain_svc` |
| `EVAL_DB_PASSWORD` | Setup and the separate B-05 runner | Password for read-only `eval_runner` |
| `MIGRATION_DB_PASSWORD` | Setup and explicit migration or seed commands | Password for `db_migrator` |
| `DATABASE_URL` | Each FastAPI service | Its own database role and address, supplied by Compose |
| `PGPASSWORD` | Each database client | That role's password, read by the PostgreSQL driver |
| `ROOT_PATH` | Each FastAPI service | Public gateway path prefix |

`.env` is ignored by Git. The example contains placeholders, and Docker build
contexts allow only source and dependency files. The browser receives public
relative API paths. Each application container receives its own runtime identity.
The setup job receives administrator and provisioning credentials. Migration and
evaluation credentials belong to their separate commands or runner processes.
`PGPASSWORD` carries the raw password independently of `DATABASE_URL`, so special
characters in a password do not need URL encoding.

## Database identities

| Role | Access |
| --- | --- |
| `auth_svc` | Owns the `auth` schema and its tables |
| `agent_svc` | Owns the `agent` checkpoint schema and its tables |
| `domain_svc` | CRUD on tables and sequence usage in `domain` |
| `eval_runner` | Read-only access to Golden Dataset labels in `eval` |
| `db_migrator` | Owns `domain` and `eval`, creates or upgrades their tables, and seeds data |

The PostgreSQL administrator runs the idempotent `db-setup` job before services
start. Provisioning configures existing tables and default privileges for future
migrations. Each service role is restricted to its own schema, and the Agent
retrieves business evidence through scoped Domain APIs.

The job also works with an existing PostgreSQL volume. Keep that volume's original
`POSTGRES_USER` and `POSTGRES_PASSWORD` in `.env`, and add the five new role
passwords. Provisioning transfers existing application tables to the intended
schema owners. PostgreSQL data persists in the `postgres_data` named volume.
Changing the administrator password in `.env` still requires updating that
database role separately. Service passwords are reapplied by the setup job.

Run migrations and the C-01 reset or seed command with a
`DATABASE_URL` for `db_migrator` and `PGPASSWORD` set from `MIGRATION_DB_PASSWORD`.
Run the B-05 scorer with the `eval_runner` identity and `EVAL_DB_PASSWORD` in its
own process, keeping those credentials outside the Agent container.

The C-01 reset command drops and recreates both schemas, which removes their
grants. After an intentional reset, reapply permissions before restarting APIs.
From `a-01-scaffold`, run

```powershell
docker compose run --rm db-setup
```

Verify cross-schema denial and future migration grants with the transactional
check below. It creates temporary probe tables and rolls the transaction back.

```powershell
docker compose run --rm --entrypoint psql db-setup -X -v ON_ERROR_STOP=1 -f /setup/verify-permissions.sql
```

The gateway binds to `127.0.0.1` for local development. Only the gateway publishes
a host port. Agree on external deployment settings with the Platform owner.

## Work on a component

Each service has its own Dockerfile and requirements. Rebuild the component you
change, then verify the gateway endpoint again.

```powershell
docker compose up --build -d auth
docker compose logs --tail 50 auth
```

Use the same command with `agent`, `domain`, or `frontend`. The gateway resolves
service addresses through Docker DNS when containers are recreated.

For frontend-only development, run `npm ci` and `npm run dev` in `frontend`.
The integrated service checks run through the Compose gateway.

## Stop and troubleshoot

```powershell
docker compose logs --tail 50 gateway domain postgres
docker compose down
```

`docker compose down` preserves the database volume. If the Docker engine cannot
be reached, start Docker Desktop and wait until the Linux engine is ready.
If port 18080 is occupied, change `APP_PORT` in `.env` and recreate the gateway.

If a company network causes certificate verification failures during image
builds, the Dockerfiles accept an optional BuildKit secret named `build_ca`.
Provide a PEM bundle containing your trusted network CA when building the images.
The certificate is mounted only for dependency installation. For example, build
Auth with the command below, then repeat for Agent, Domain, and Frontend using
their corresponding image tags and folders before starting Compose.

```powershell
docker build --secret id=build_ca,src=C:/path/to/trusted-ca.pem -t retail-internal-ai-agent-auth services/auth
```

## Sprint handoff

A-02 adds login and JWT/RBAC to Auth. B-01 finalizes business request and response
contracts, and later agent tickets add LangGraph. C-01 adds SQLAlchemy models and
seeded store data to Domain. D tickets extend the React workspace. Use the health
and readiness endpoints to verify integration while those features are built.
