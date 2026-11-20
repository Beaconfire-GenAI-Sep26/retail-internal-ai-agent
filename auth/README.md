# Auth Service

Owns accounts, role/store grants and rotating refresh sessions in the `auth`
schema. The FastAPI entry point is `auth.app.main:app`. Run Compose from the
repository root with `docker compose up --build auth`.

Endpoints: `/login`, `/me`, `/refresh`, `/logout`, `/health`, `/ready`. The gateway
adds the public `/auth` prefix. Login/refresh issue expiring HS256 access tokens;
refresh credentials live in an HttpOnly cookie and only their hashes enter the
database. Passwords use scrypt.

Dependencies are in `requirements.txt`. The root Docker context includes `auth/`
and `shared/`; it does not copy another service's implementation. For direct
development, install the requirements and run `uvicorn auth.app.main:app --root-path /auth` from
the repository root with the service's JWT and database environment configured.

See [authentication.md](../docs/authentication.md) for configuration, account
seeding, CSRF, rotation/replay behavior and access-token revocation limits.
