"""Privacy-safe telemetry shared by services. Never put credentials in this context."""
import json
import logging
import os
import re
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from uuid import uuid4

REDACTED = "[REDACTED]"


class StaticPrompt(str):
    """Source-controlled prompt text only. Never wrap runtime/user evidence."""


_context = ContextVar("log_context", default={})
_service = "application"
_request_id = re.compile(r"[A-Za-z0-9._-]{1,128}")
_token_counters = {"input_tokens", "output_tokens", "total_tokens", "max_tokens",
                   "cache_read_input_tokens", "cache_creation_input_tokens",
                   "ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens"}
_private_key = re.compile(
    r"authorization|cookie|password|secret|token|api_key|credential|"
    r"email|phone|address|customer_comments|customer_name|merchant_name|"
    r"display_name|username|first_name|last_name|full_name|^name$|"
    r"^text$|^content$|^reply_text$|^question_text$|^summary$|^rationale$|"
    r"^assessment$|^statement$|^notes?$|^description$|^message$|^prompt$|^system$|"
    r"^purpose$|^why_asked$|^reply_claims$|^headline$|^guard_feedback$|^gate_feedback$|"
    r"^if_true$|^if_false$|^reason$|^error_message$",
    re.I,
)
_phone_pattern = re.compile(r"(?<!\w)(?:\+?\d[\d ().-]{7,}\d)(?!\w)")
_patterns = [
    re.compile(r"\bBearer\s+[^\s\"',;]+", re.I),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
    re.compile(r"\b(?:sk|pk)-(?:ant-|lf-)?[A-Za-z0-9_-]+\b"),
    re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"),
    _phone_pattern,
    re.compile(r"\b\d+\s+(?:[A-Za-z]+\s+){1,5}(?:street|st|avenue|ave|road|rd|lane|ln|drive|dr|blvd)\b", re.I),
    re.compile(r"(?i)\b(?:password|secret|api[_-]?key|access[_-]?token|refresh[_-]?token)\s*[:=]\s*[^\s,;]+"),
]


def correlation_id(value):
    return value if isinstance(value, str) and _request_id.fullmatch(value) else uuid4().hex


def safe_id(value, kind):
    patterns = {"case_id": r"CASE-\d{4,}", "investigation_id": r"INV-[A-Za-z0-9-]{1,64}",
                "trace_id": r"[a-f0-9]{32}"}
    return value if isinstance(value, str) and re.fullmatch(patterns[kind], value) else None


def scrub_text(value, *, identifier=False):
    for pattern in _patterns:
        if identifier and pattern is _phone_pattern:  # a validated opaque ID may be all digits
            continue
        value = pattern.sub(REDACTED, value)
    # Also remove configured secrets, including opaque service/DB passwords.
    for key, secret in os.environ.items():
        if re.search(r"PASSWORD|SECRET|TOKEN|API_KEY", key) and len(secret) >= 8:
            value = value.replace(secret, REDACTED)
    return value[:4096]


def redact(data, *, _depth=0):
    """Drop private/prose fields; scrub strings; never repr unknown objects.

    Prompts must be represented as a static template/version plus structured,
    redacted evidence. Message content and customer/merchant prose are withheld
    entirely: regexes alone cannot reliably identify names in natural language.
    """
    if _depth > 16:
        return REDACTED
    if isinstance(data, dict):
        result = {}
        for key, value in list(data.items())[:200]:
            key = str(key)
            normalized = re.sub(r"(?<=[a-z])(?=[A-Z])", "_", key).lower().replace("-", "_")
            # Usage counters aren't credentials.
            counter = normalized in _token_counters and isinstance(value, (int, float))
            private = _private_key.search(normalized) and not counter
            if normalized in {"request_id", "case_id", "investigation_id", "trace_id"} and isinstance(value, str):
                valid = _request_id.fullmatch(value) if normalized == "request_id" else safe_id(value, normalized)
                clean = scrub_text(value, identifier=True) if valid else REDACTED
            else:
                clean = REDACTED if private else redact(value, _depth=_depth + 1)
            result[scrub_text(key)] = clean
        return result
    if isinstance(data, (list, tuple)):
        return [redact(value, _depth=_depth + 1) for value in data[:200]]
    if isinstance(data, str):
        if isinstance(data, StaticPrompt):
            return StaticPrompt(scrub_text(data))
        # SDK callbacks can deliver JSON serialized state as strings.
        if data.lstrip().startswith(("{", "[")):
            try:
                return redact(json.loads(data), _depth=_depth + 1)
            except (ValueError, RecursionError):
                pass
        # Unknown prose is withheld too: a name/address can occur under any key.
        if re.search(r"\s", data):
            return REDACTED
        # Keep ISO dates/timestamps out of the phone-number heuristic.
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:T[\d:.+Z-]+)?", data):
            return data
        return scrub_text(data)
    if data is None or isinstance(data, (bool, int, float)):
        return data
    return REDACTED


def log_context():
    return dict(_context.get())


def bind_context(**values):
    """Enrich only this task's context. Use context_scope at request/run boundaries."""
    _context.set({**_context.get(), **{k: v for k, v in values.items() if v is not None}})


@contextmanager
def context_scope(**values):
    token = _context.set({**_context.get(), **values})
    try:
        yield
    finally:
        _context.reset(token)


class JSONFormatter(logging.Formatter):
    def format(self, record):
        context = {**log_context(), **getattr(record, "context", {})}
        # Third-party messages can contain SQL parameters, prompts and personal
        # data. Retain their logger and severity without exporting arbitrary prose.
        event = record.getMessage() if record.name == "application" else "library.log"
        payload = {"timestamp": datetime.now(timezone.utc).isoformat(), "level": record.levelname,
                   "service": getattr(record, "service", None) or context.get("service", _service),
                   "logger": record.name, "event": scrub_text(event),
                   "request_id": None, "case_id": None, "investigation_id": None,
                   "trace_id": None, **context, **getattr(record, "fields", {})}
        if record.exc_info:
            # Exception messages and stacks can embed SQL parameters, URLs and bodies.
            payload["error_type"] = record.exc_info[0].__name__
        return json.dumps(redact(payload), ensure_ascii=True, allow_nan=False)


def configure_logging(service):
    global _service
    _service = service
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    level = level if level in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"} else "INFO"
    root = logging.getLogger()
    handler = next((h for h in root.handlers if getattr(h, "retail_json", False)), None)
    if handler is None:
        handler = logging.StreamHandler(sys.stdout)
        handler.retail_json = True
        root.addHandler(handler)
    for existing in root.handlers:
        existing.setFormatter(JSONFormatter())
    root.setLevel(level)
    # Uvicorn's access lines contain unfiltered query strings and client IPs.
    logging.getLogger("uvicorn.access").disabled = True
    for name in ("uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
    for name in ("httpx", "httpcore", "httpx2", "httpcore2", "anthropic", "langfuse", "opentelemetry"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
        logger.setLevel(logging.WARNING)
    return logging.LoggerAdapter(logging.getLogger("application"), {"service": service})


def log_event(event, *, level=logging.INFO, **fields):
    logging.getLogger("application").log(level, event, extra={"fields": fields})
