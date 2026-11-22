# Platform integration

Launch the stack using root `compose.yaml` and `.env`. API services live in
`auth/`, `agent/`, `domain/`; the analyst workspace lives in `frontend/`.

`gateway/` contains the Nginx image and routing configuration. It strips the
public API prefixes, preserves request IDs, blocks Domain's internal routes and
strips browser-supplied service tokens. It owns no business authorization logic.

`postgres/001-service-roles.sh` initializes isolated schemas and service roles.
It is idempotent and can be run explicitly against existing volumes without
dropping data. The root README and [authentication guide](../docs/authentication.md)
describe setup and permissions to restore after a Domain reset.

Both shell scripts are tracked as executable (`100755`), with LF line endings
enforced by `.gitattributes`. The init wrapper also supports being sourced:
Postgres sources `.sh` files when a bind mount reports them as non-executable.
It must call `sh /setup/provision.sh` without `exec`, so control returns to the
Postgres entrypoint and the server finishes starting.

To check the repository modes on any host, including Windows:

```bash
git ls-files --stage platform/postgres/001-service-roles.sh platform/postgres/provision.sh
```

Both lines should begin with `100755`. For an existing volume, rerun provisioning
without deleting data:

```bash
docker compose exec postgres sh /docker-entrypoint-initdb.d/001-service-roles.sh
```

If initialization previously stopped, first run `docker compose up -d postgres`,
then the command above: Postgres skips init scripts once its data directory exists.
Run `docker compose up -d` afterward to start the remaining services.

Fresh-volume verification (November 22, 2026) used isolated Compose projects and
test credentials with the repository's `postgres:17-alpine` image:

| Script delivery | Result |
| --- | --- |
| Original committed `644` scripts | Init wrapper was sourced; `exec` replaced the entrypoint and the container exited with code 0 after provisioning |
| Fixed scripts with Git mode `755` | Healthy Postgres; initialization completed |
| Fixed scripts forced to `644` | Healthy Postgres; sourcing returned to the entrypoint |
| Fixed scripts through the actual Compose bind mounts (Docker Desktop reported `777`) | Healthy Postgres; initialization completed |

All three fixed variants passed `verify-permissions.sql`, password logins for
`auth_svc`, `domain_svc`, and `agent_svc`, and repeat provisioning without stopping
the server. The reported exit 126 was not reproduced on this host. These checks
used disposable volumes; the application's existing volume was left intact.

All backend images build from the repository root so they can include `shared/`.
The root `.dockerignore` limits this context to backend source/dependencies and
excludes local configuration, virtual environments and caches. The gateway and
frontend have their own build contexts.

For a corporate CA, backend Dockerfiles accept the BuildKit secret `build_ca`.
From the repository root, for example:

```bash
docker build \
  --secret "id=build_ca,src=$HOME/path/to/trusted-ca.pem" \
  -f auth/Dockerfile \
  -t retail-internal-ai-agent-auth .
```

The Agent installs from its uv lockfile; Auth and Domain install from each
service's requirements. Secrets are supplied at runtime and never enter the
frontend build. Only the gateway exposes a host port (`APP_PORT`, default 18080).
