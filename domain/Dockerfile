FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UVICORN_ROOT_PATH=/domain
WORKDIR /app
COPY domain/requirements.txt .
RUN --mount=type=secret,id=build_ca \
    if [ -f /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi; \
    pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home appuser
COPY domain ./domain
COPY shared ./shared
USER appuser
EXPOSE 8000
CMD ["uvicorn", "domain.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
