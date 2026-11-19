# syntax=docker/dockerfile:1.7
# Agent Service. Same base image, port and non-root user as the A-01 scaffold; dependencies come
# from uv.lock only. An optional BuildKit secret `build_ca` adds a trusted CA for networks that
# intercept TLS:  docker build --secret id=build_ca,src=C:/path/to/ca.pem -t retail-agent agent/
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=secret,id=build_ca \
    if [ -f /run/secrets/build_ca ]; then export SSL_CERT_FILE=/run/secrets/build_ca; fi; \
    uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY tests/fixtures/domain ./fixtures/domain
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev \
    && useradd --create-home appuser

ENV AGENT_FIXTURES_DIR=/app/fixtures/domain \
    PATH="/app/.venv/bin:$PATH" \
    ROOT_PATH=/agent

USER appuser
EXPOSE 8000
CMD ["sh", "-c", "exec /app/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --root-path \"$ROOT_PATH\""]
