"""A Domain stand-in that answers from JSON fixtures (AGENT_DOMAIN_MODE=fixtures).

Layout under the fixtures root:
  common/catalog.json                 ActionCatalogEntry[]
  <STORE>/case.json                   CaseDetail
  <STORE>/menu.json                   MenuItem[]
  <STORE>/overview.json               ToolResult for the whole window
  <STORE>/fraud_signals.json          ToolResult
  <STORE>/checks.json                 [{"match": {...}, "result": ToolResult}]

A query matches an entry on the tool, group_by, evidence_type and the non-date filter fields
(compare_periods: target, control and split_date). When several entries match, the one whose
window is closest to the requested dates wins. Unmatched queries return an insufficient result
with a "no fixture" note and are counted in `misses`.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.contracts.models import (
    ActionCatalogEntry,
    CaseDetail,
    EvidenceResolveResponse,
    InvestigationStatusUpdate,
    MenuItem,
    Proposal,
    ProposalCreate,
    ToolResult,
    Window,
)
from app.domain.client import DomainError

DATE_KEYS = ("start", "end")


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


class _StoreFixtures:
    def __init__(self, folder: Path):
        self.folder = folder
        self.case = CaseDetail.model_validate(_load(folder / "case.json"))
        self.menu = [MenuItem.model_validate(m) for m in _load(folder / "menu.json")]
        self.overview = ToolResult.model_validate(_load(folder / "overview.json"))
        self.fraud_signals = ToolResult.model_validate(_load(folder / "fraud_signals.json"))
        self.checks: list[dict[str, Any]] = [
            {"match": entry["match"], "result": ToolResult.model_validate(entry["result"])}
            for entry in _load(folder / "checks.json")
        ]
        self.timezone = ZoneInfo(self.case.store.timezone)
        self.known_ids = self._collect_ids()

    def _collect_ids(self) -> set[str]:
        ids: set[str] = set()
        results = [self.overview, self.fraud_signals, *(c["result"] for c in self.checks)]
        for result in results:
            ids.update(result.evidence_ids)
            ids.update(e.evidence_id for e in result.evidence)
        return ids


def _strip_dates(scope: dict[str, Any] | None) -> dict[str, Any] | None:
    if scope is None:
        return None
    return {k: v for k, v in scope.items() if k not in DATE_KEYS}


def _days(a: str, b: str) -> int:
    try:
        return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)
    except ValueError:
        return 10_000


def _request_window(tool: str, request: dict[str, Any]) -> tuple[str, str] | None:
    if tool == "compare_periods":
        return None
    flt = request.get("filter", request)
    if "start" in flt and "end" in flt:
        return flt["start"], flt["end"]
    return None


def _matches(match: dict[str, Any], tool: str, request: dict[str, Any]) -> bool:
    if match.get("tool") != tool:
        return False
    for key in ("group_by", "evidence_type"):
        if key in match and match[key] != request.get(key):
            return False
    if tool == "compare_periods":
        if match.get("target", {}) != request.get("target", {}):
            return False
        if match.get("control") != request.get("control"):
            return False
        allowed = match.get("split_date")
        return allowed is None or request.get("split_date") in allowed
    if "filter" in request:
        return match.get("filter", {}) == _strip_dates(request["filter"])
    return True


class FixtureDomainClient:
    """Implements both DomainClient and DomainPort. `bind` returns the client itself."""

    def __init__(
        self,
        root: Path,
        *,
        variants: dict[str, dict[str, str]] | None = None,
        faults: dict[str, DomainError] | None = None,
    ):
        self.root = Path(root)
        self.catalog = [ActionCatalogEntry.model_validate(e) for e in _load(self.root / "common" / "catalog.json")]
        self.stores: dict[str, _StoreFixtures] = {}
        for folder in sorted(p for p in self.root.iterdir() if p.is_dir() and p.name != "common"):
            fixtures = _StoreFixtures(folder)
            self.stores[fixtures.case.store_id] = fixtures
        self.faults = dict(faults or {})
        self.calls: list[dict[str, Any]] = []
        self.misses: list[dict[str, Any]] = []
        self.status_updates: list[dict[str, Any]] = []
        self.proposals: dict[str, Proposal] = {}
        for store_id, files in (variants or {}).items():
            for name, filename in files.items():
                result = ToolResult.model_validate(_load(self.stores[store_id].folder / filename))
                setattr(self.stores[store_id], name, result)
                self.stores[store_id].known_ids |= set(result.evidence_ids)

    # DomainClient
    def bind(self, *, token: str, request_id: str, investigation_id: str | None) -> FixtureDomainClient:
        return self

    async def aclose(self) -> None:
        return None

    # helpers
    def _record(self, method: str, **args: Any) -> None:
        self.calls.append({"method": method, **args})
        fault = self.faults.get(method)
        if fault is not None:
            raise fault

    def _store(self, store_id: str) -> _StoreFixtures:
        if store_id not in self.stores:
            raise DomainError(404, "NOT_FOUND", f"No fixtures for store {store_id}.")
        return self.stores[store_id]

    def case_for_store(self, store_id: str) -> CaseDetail:
        return self._store(store_id).case

    def _lookup(self, store_id: str, tool: str, request: dict[str, Any]) -> ToolResult:
        store = self._store(store_id)
        candidates = [c for c in store.checks if _matches(c["match"], tool, request)]
        wanted = _request_window(tool, request)
        if not candidates:
            self.misses.append({"store_id": store_id, "tool": tool, "request": request})
            start, end = wanted or (request.get("split_date", ""), request.get("split_date", ""))
            return ToolResult(
                tool=tool,
                store_id=store_id,
                window=Window(start=start, end=end),
                data_sufficient=False,
                headline="No fixture matches this query.",
                notes=["No fixture for this query. Fixtures mode answers only the queries in the fixture files."],
            )
        if wanted:
            candidates.sort(
                key=lambda c: _days(c["result"].window.start, wanted[0]) + _days(c["result"].window.end, wanted[1])
            )
        result = candidates[0]["result"].model_copy(deep=True)
        if wanted and (result.window.start, result.window.end) != wanted:
            result.notes.append(
                f"Fixture data covers {result.window.start} to {result.window.end}; "
                f"the request asked for {wanted[0]} to {wanted[1]}."
            )
        return result

    # DomainPort
    async def get_case(self, case_id: str) -> CaseDetail:
        self._record("get_case", case_id=case_id)
        for store in self.stores.values():
            if store.case.case_id == case_id:
                case = store.case.model_copy(deep=True)
                case.proposals = [p for p in self.proposals.values() if p.case_id == case_id]
                return case
        raise DomainError(404, "CASE_NOT_FOUND", f"Case {case_id} was not found.")

    async def get_menu(self, store_id: str) -> list[MenuItem]:
        self._record("get_menu", store_id=store_id)
        return [m.model_copy() for m in self._store(store_id).menu]

    async def get_catalog(self) -> list[ActionCatalogEntry]:
        self._record("get_catalog")
        return [e.model_copy() for e in self.catalog]

    async def store_overview(self, store_id: str, start: str, end: str) -> ToolResult:
        self._record("store_overview", store_id=store_id, start=start, end=end)
        result = self._store(store_id).overview.model_copy(deep=True)
        if (result.window.start, result.window.end) != (start, end):
            result.notes.append(
                f"Fixture data covers {result.window.start} to {result.window.end}; "
                f"the request asked for {start} to {end}."
            )
        return result

    async def fraud_signals(self, store_id: str, start: str, end: str) -> ToolResult:
        self._record("fraud_signals", store_id=store_id, start=start, end=end)
        return self._store(store_id).fraud_signals.model_copy(deep=True)

    async def event_log(self, store_id: str, start: str, end: str, event_type: list[str]) -> ToolResult:
        self._record("event_log", store_id=store_id, start=start, end=end, event_type=event_type)
        store = self._store(store_id)
        base = next((c["result"] for c in store.checks if c["match"].get("tool") == "event_log"), None)
        if base is None:
            return self._lookup(store_id, "event_log", {"start": start, "end": end, "event_type": event_type})
        lo, hi = date.fromisoformat(start), date.fromisoformat(end)
        kept = []
        for ev in base.evidence:
            started = datetime.fromisoformat(ev.attributes["started_at"].replace("Z", "+00:00"))
            local_day = started.astimezone(store.timezone).date()
            if lo <= local_day <= hi and (not event_type or ev.attributes.get("event_type") in event_type):
                kept.append(ev)
        kinds = ", ".join(event_type) if event_type else "all types"
        return ToolResult(
            tool="event_log",
            store_id=store_id,
            window=Window(start=start, end=end),
            eligible_orders=0,
            pending_claims=0,
            data_sufficient=True,
            headline=f"{len(kept)} events from {start} to {end} ({kinds}).",
            metrics=[],
            evidence_ids=[e.evidence_id for e in kept],
            evidence=kept,
            notes=[],
        )

    async def claim_breakdown(self, store_id: str, request: dict[str, Any]) -> ToolResult:
        self._record("claim_breakdown", store_id=store_id, request=request)
        return self._lookup(store_id, "claim_breakdown", request)

    async def compare_periods(self, store_id: str, request: dict[str, Any]) -> ToolResult:
        self._record("compare_periods", store_id=store_id, request=request)
        return self._lookup(store_id, "compare_periods", request)

    async def evidence_sample(self, store_id: str, request: dict[str, Any]) -> ToolResult:
        self._record("evidence_sample", store_id=store_id, request=request)
        result = self._lookup(store_id, "sample_evidence", request)
        limit = int(request.get("limit", 10))
        result.evidence = result.evidence[:limit]
        result.evidence_ids = [e.evidence_id for e in result.evidence]
        return result

    async def cancellation_breakdown(self, store_id: str, request: dict[str, Any]) -> ToolResult:
        self._record("cancellation_breakdown", store_id=store_id, request=request)
        return self._lookup(store_id, "cancellation_breakdown", request)

    async def resolve_evidence(self, store_id: str, evidence_ids: list[str]) -> EvidenceResolveResponse:
        self._record("resolve_evidence", store_id=store_id, evidence_ids=evidence_ids)
        known = self._store(store_id).known_ids
        valid = [e for e in evidence_ids if e in known]
        invalid = [{"evidence_id": e, "reason": "not_found"} for e in evidence_ids if e not in known]
        return EvidenceResolveResponse(valid=valid, invalid=invalid)

    async def create_proposal(self, case_id: str, body: ProposalCreate) -> Proposal:
        self._record("create_proposal", case_id=case_id, body=body.model_dump(mode="json"))
        if any(p.case_id == case_id and p.status == "pending" for p in self.proposals.values()):
            raise DomainError(409, "PROPOSAL_PENDING", f"Case {case_id} already has a pending proposal.")
        proposal_id = f"PROP-{len(self.proposals) + 1:04d}"
        proposal = Proposal(
            proposal_id=proposal_id,
            case_id=case_id,
            investigation_id=body.investigation_id,
            kind=body.kind,
            version=1,
            status="pending",
            content=body.content.model_dump(mode="json"),
            evidence_ids=list(body.evidence_ids),
        )
        self.proposals[proposal_id] = proposal
        return proposal

    async def report_investigation_status(self, case_id: str, body: InvestigationStatusUpdate) -> None:
        self._record("report_investigation_status", case_id=case_id, body=body.model_dump(mode="json"))
        self.status_updates.append({"case_id": case_id, **body.model_dump(mode="json")})
