FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.8.3 /uv /bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/app/.venv \
    UVICORN_ROOT_PATH=/agent
WORKDIR /app
COPY agent/pyproject.toml agent/uv.lock ./agent/
RUN --mount=type=secret,id=build_ca \
    if [ -f /run/secrets/build_ca ]; then export SSL_CERT_FILE=/run/secrets/build_ca; fi; \
    uv sync --frozen --no-dev --project agent \
    && useradd --create-home appuser
COPY agent ./agent
COPY shared ./shared
USER appuser
EXPOSE 8000
CMD ["/app/.venv/bin/uvicorn", "agent.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
