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
Set-Location planned/a-01-scaffold
```

Create your local configuration if `.env` does not already exist.

```powershell
Copy-Item .env.example .env
```

Set `POSTGRES_PASSWORD` in `.env` to a local password, then run

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

All six containers should become healthy. Every endpoint should return
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
| `POSTGRES_DB` | PostgreSQL and Domain | Database name |
| `POSTGRES_USER` | PostgreSQL and Domain | Local database user |
| `POSTGRES_PASSWORD` | PostgreSQL and Domain | Required runtime password |
| `POSTGRES_HOST` | Domain | Set to `postgres` by Compose |
| `POSTGRES_PORT` | Domain | Set to `5432` by Compose |
| `ROOT_PATH` | Each FastAPI service | Public gateway path prefix |

`.env` is ignored by Git. The example contains placeholders, and Docker build
contexts allow only source and dependency files. The browser receives public
relative API paths. Database credentials are supplied only to PostgreSQL and
Domain at runtime. PostgreSQL data persists in the `postgres_data` named volume.
Changing the password in `.env` does not change credentials in an existing
database volume. Update the database role before restarting with changed
credentials.

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
