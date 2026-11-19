"""JSON log lines that carry the request, case and investigation IDs."""

from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
case_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("case_id", default=None)
investigation_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "investigation_id", default=None
)

_CONTEXT_FIELDS = (
    ("request_id", request_id_var),
    ("case_id", case_id_var),
    ("investigation_id", investigation_id_var),
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, var in _CONTEXT_FIELDS:
            value = var.get()
            if value:
                payload[key] = value
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "info") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpcore", "httpx2", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def log_event(logger: logging.Logger, level: int, msg: str, **fields: Any) -> None:
    """Log one structured line. Never pass tokens or customer text here."""
    logger.log(level, msg, extra={"fields": fields})
