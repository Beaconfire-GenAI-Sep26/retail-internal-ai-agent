"""JSON log lines that carry the request, case and investigation IDs."""

from __future__ import annotations

import contextvars
import json
import logging
from typing import Any

from shared.observability import JSONFormatter, configure_logging as configure_shared_logging

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


class JsonFormatter(JSONFormatter):
    """Keep the Agent formatter API while applying the shared redaction policy."""

    def format(self, record: logging.LogRecord) -> str:
        payload = json.loads(super().format(record))
        payload["level"] = payload["level"].lower()
        return json.dumps(payload)


def configure_logging(level: str = "info") -> None:
    configure_shared_logging("agent")
    logging.getLogger().setLevel(level.upper())


def log_event(logger: logging.Logger, level: int, msg: str, **fields: Any) -> None:
    """Log one structured line. Never pass tokens or customer text here."""
    context = {key: var.get() for key, var in _CONTEXT_FIELDS if var.get() is not None}
    logger.log(level, msg, extra={"fields": {"event": msg.replace(" ", "_"), **fields},
                                 "context": context})
