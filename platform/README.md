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
