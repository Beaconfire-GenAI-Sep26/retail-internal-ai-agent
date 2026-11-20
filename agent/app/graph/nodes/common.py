"""Helpers shared by the nodes."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from agent.app.domain.client import DomainError
from agent.app.errors import DOMAIN_REJECTED, RUN_TIMEOUT, UNAUTHENTICATED, UPSTREAM_UNAVAILABLE
from agent.app.graph.policy import scrub
from agent.app.tools.registry import canonical_key, signature


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def timeout_error() -> dict[str, str]:
    return {"code": RUN_TIMEOUT, "message": "The investigation ran past AGENT_RUN_TIMEOUT_SECONDS."}


def domain_error(exc: DomainError, where: str) -> dict[str, str]:
    if exc.unavailable:
        code = UPSTREAM_UNAVAILABLE
    elif exc.status == 401:
        code = UNAUTHENTICATED
    else:
        code = DOMAIN_REJECTED
    return {"code": code, "message": f"{where}: Domain returned {exc.status} {exc.code}: {exc.message}"}


def scrub_result(result: dict[str, Any]) -> dict[str, Any]:
    """Remove emails and phone numbers from Domain text before it enters state."""
    result["headline"] = scrub(result.get("headline")) or ""
    result["notes"] = [scrub(n) or "" for n in result.get("notes", [])]
    for record in result.get("evidence", []):
        record["summary"] = scrub(record.get("summary")) or ""
        attrs = record.get("attributes", {})
        for key in ("customer_comments", "description", "text"):
            if attrs.get(key):
                attrs[key] = scrub(attrs[key])
    return result


def local_date(ts: str, tz: str) -> date:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(ZoneInfo(tz)).date()


def window_end_date(value: str, tz: str) -> date:
    """The store-local date of CaseSummary.window_end, a UTC timestamp or a date.

    A timestamp at exactly local midnight is an exclusive end, so the window ends the day before.
    """
    if len(value) == 10:
        return date.fromisoformat(value)
    local = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(ZoneInfo(tz))
    if local.time() == time(0, 0):
        return (local - timedelta(days=1)).date()
    return local.date()


def make_record(
    check_id: str,
    *,
    source: str,
    kind: str,
    tool: str,
    request: dict[str, Any],
    result: dict[str, Any],
    purpose: str,
    discriminates: list[str] | None = None,
    expectations: list[dict[str, str]] | None = None,
    challenges: str | None = None,
    domain_rejected: bool = False,
) -> dict[str, Any]:
    expectations = list(expectations or [])
    return {
        "check_id": check_id,
        "source": source,
        "kind": kind,
        "tool": tool,
        "request": request,
        "canonical_key": canonical_key(tool, request),
        "signature": signature(tool, request),
        "purpose": purpose,
        "discriminates": list(discriminates or []),
        "expectations": expectations,
        "challenges": challenges,
        "result": result,
        "matched": {},
        "needs_match": bool(expectations),
        "domain_rejected": domain_rejected,
        "at": now_iso(),
    }


def ledger_entries(result: dict[str, Any], tz: str) -> list[dict[str, Any]]:
    out = []
    for record in result.get("evidence", []):
        if record.get("type") != "operational_event":
            continue
        attrs = record.get("attributes", {})
        if not attrs.get("started_at"):
            continue
        out.append({
            "evidence_id": record["evidence_id"],
            "event_type": attrs.get("event_type", ""),
            "start_date": local_date(attrs["started_at"], tz).isoformat(),
            "end_date": local_date(attrs["ended_at"], tz).isoformat() if attrs.get("ended_at") else None,
            "description": attrs.get("description", ""),
        })
    return out
