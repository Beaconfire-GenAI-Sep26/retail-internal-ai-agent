"""How the agent talks to the Domain Service.

`DomainPort` is one investigation's view of Domain: every call carries that investigation's
forwarded JWT, request ID and investigation ID. `HttpDomainClient` implements it over the endpoints
in contracts.md. `FixtureDomainClient` (fixtures.py) implements it from JSON files.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from agent.app.contracts.models import (
    ActionCatalogEntry,
    CaseDetail,
    EvidenceResolveResponse,
    InvestigationStatusUpdate,
    MenuItem,
    Proposal,
    ProposalCreate,
    ToolResult,
)
from agent.app.logs import log_event
from agent.app.domain_client import DomainClient as ScopedDomainClient, domain_request
from shared.security import APIError, JWTSettings, require_store, verify_token

logger = logging.getLogger("agent.domain")

# A route in Domain's access policy that has no handler yet (the C-03 routes) gets this generic 404.
# Application 404s use their own codes or messages ("Resource not found."), and a route outside the
# policy gets 403, so neither looks like this.
ROUTE_MISSING_MESSAGES = frozenset({"Not Found"})
# POST /evidence/resolve takes at most this many IDs per request.
RESOLVE_LIMIT = 200


class DomainError(Exception):
    """A Domain call failed. `status` is the HTTP status, or 503 when Domain was unreachable."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        *,
        method: str = "",
        path: str = "",
    ):
        super().__init__(f"{status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}
        self.method = method
        self.path = path

    @property
    def unavailable(self) -> bool:
        return self.status >= 500

    @property
    def rejected(self) -> bool:
        return self.status == 422

    @property
    def route_missing(self) -> bool:
        """Domain doesn't have this route yet, as opposed to a real 404 for a missing resource."""
        return (
            self.status == 404
            and self.code == "NOT_FOUND"
            and self.message in ROUTE_MISSING_MESSAGES
            and not self.details
        )


class DomainPort(Protocol):
    async def get_case(self, case_id: str) -> CaseDetail: ...
    async def get_menu(self, store_id: str) -> list[MenuItem]: ...
    async def get_catalog(self) -> list[ActionCatalogEntry]: ...
    async def store_overview(self, store_id: str, start: str, end: str) -> ToolResult: ...
    async def event_log(self, store_id: str, start: str, end: str, event_type: list[str]) -> ToolResult: ...
    async def claim_breakdown(self, store_id: str, request: dict[str, Any]) -> ToolResult: ...
    async def compare_periods(self, store_id: str, request: dict[str, Any]) -> ToolResult: ...
    async def evidence_sample(self, store_id: str, request: dict[str, Any]) -> ToolResult: ...
    async def cancellation_breakdown(self, store_id: str, request: dict[str, Any]) -> ToolResult: ...
    async def fraud_signals(self, store_id: str, start: str, end: str) -> ToolResult: ...
    async def resolve_evidence(self, store_id: str, evidence_ids: list[str]) -> EvidenceResolveResponse: ...
    async def create_proposal(self, case_id: str, body: ProposalCreate) -> Proposal: ...
    async def report_investigation_status(self, case_id: str, body: InvestigationStatusUpdate) -> None: ...


class DomainClient(Protocol):
    def bind(self, *, token: str, request_id: str, investigation_id: str | None, store_id: str | None = None,
             case_id: str | None = None, max_retries: int | None = None) -> DomainPort: ...
    async def aclose(self) -> None: ...


def _p(value: str) -> str:
    return quote(value, safe="")


class HttpDomainClient:
    """Shared HTTP client. `bind` returns the per-investigation `DomainPort`."""

    def __init__(
        self,
        base_url: str,
        service_token: str,
        *,
        timeout: float = 10.0,
        max_retries: int = 2,
        backoff_seconds: float = 0.5,
        transport: httpx.AsyncBaseTransport | None = None,
        jwt_settings: JWTSettings | None = None,
    ):
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout, transport=transport)
        self._service_token = service_token
        self._jwt_settings = jwt_settings or JWTSettings.from_env()
        self._max_retries = max_retries
        self._backoff = backoff_seconds

    def bind(self, *, token: str, request_id: str, investigation_id: str | None, store_id: str | None = None,
             case_id: str | None = None, max_retries: int | None = None) -> DomainPort:
        """`max_retries` overrides the client's retry count for this binding (0 for one attempt)."""
        return _BoundHttpDomain(self, token=token, request_id=request_id, investigation_id=investigation_id,
                                store_id=store_id, case_id=case_id, max_retries=max_retries)

    async def aclose(self) -> None:
        await self._client.aclose()


class _BoundHttpDomain:
    def __init__(self, owner: HttpDomainClient, *, token: str, request_id: str, investigation_id: str | None,
                 store_id=None, case_id=None, max_retries: int | None = None):
        self._owner = owner
        self._store_id, self._case_id = store_id, case_id
        self._user = verify_token(token, owner._jwt_settings)
        self._token = token
        self._request_id = request_id
        self._investigation_id = investigation_id
        self._max_retries = owner._max_retries if max_retries is None else max_retries

    async def _call(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: Any = None,
        internal: bool = False,
    ) -> Any:
        owner = self._owner
        for attempt in range(self._max_retries + 1):
            if attempt:
                await asyncio.sleep(owner._backoff * 2 ** (attempt - 1))
            try:
                if self._store_id is not None and self._case_id is not None:
                    scoped = ScopedDomainClient(owner._client, access_token=self._token,
                        settings=owner._jwt_settings, store_id=self._store_id, case_id=self._case_id,
                        investigation_id=self._investigation_id or "", request_id=self._request_id,
                        service_token=owner._service_token)
                    return await scoped.request(method, path, json=body, params=params)
                # Before ownership is resolved, the only allowed operation is a
                # case lookup with the user's JWT. Every other call needs scope.
                import re
                if method != "GET" or not re.fullmatch(r"/cases/CASE-\d{4,}", path):
                    raise APIError(403, "FORBIDDEN", "Resolve case ownership before diagnostics.")
                return await domain_request(owner._client, method, path,
                    headers={"Authorization": "Bearer " + self._token, "X-Request-ID": self._request_id},
                    json=body, params=params)
            except APIError as exc:
                if exc.status < 500 or attempt == self._max_retries:
                    if exc.status >= 500:
                        log_event(logger, logging.WARNING, "domain unavailable", method=method, path=path,
                                  reason=exc.message)
                    raise DomainError(exc.status, exc.code, exc.message, exc.details,
                                      method=method, path=path) from None
        raise DomainError(503, "UPSTREAM_UNAVAILABLE", "Domain service unavailable.", method=method, path=path)

    async def get_case(self, case_id: str) -> CaseDetail:
        case = CaseDetail.model_validate(await self._call("GET", f"/cases/{_p(case_id)}"))
        try:
            require_store(self._user, case.store_id, hide=True)
        except APIError as exc:
            raise DomainError(exc.status, "CASE_NOT_FOUND", "Case not found.") from None
        self._case_id, self._store_id = case.case_id, case.store_id
        return case

    async def get_menu(self, store_id: str) -> list[MenuItem]:
        data = await self._call("GET", f"/stores/{_p(store_id)}/menu")
        return [MenuItem.model_validate(item) for item in data]

    async def get_catalog(self) -> list[ActionCatalogEntry]:
        data = await self._call("GET", "/catalog/actions")
        return [ActionCatalogEntry.model_validate(entry) for entry in data]

    async def store_overview(self, store_id: str, start: str, end: str) -> ToolResult:
        data = await self._call("GET", f"/stores/{_p(store_id)}/overview", params={"start": start, "end": end})
        return ToolResult.model_validate(data)

    async def event_log(self, store_id: str, start: str, end: str, event_type: list[str]) -> ToolResult:
        params: dict[str, Any] = {"start": start, "end": end}
        if event_type:
            params["event_type"] = list(event_type)
        data = await self._call("GET", f"/stores/{_p(store_id)}/diagnostics/events", params=params)
        return ToolResult.model_validate(data)

    async def claim_breakdown(self, store_id: str, request: dict[str, Any]) -> ToolResult:
        data = await self._call("POST", f"/stores/{_p(store_id)}/diagnostics/claim-breakdown", body=request)
        return ToolResult.model_validate(data)

    async def compare_periods(self, store_id: str, request: dict[str, Any]) -> ToolResult:
        data = await self._call("POST", f"/stores/{_p(store_id)}/diagnostics/compare-periods", body=request)
        return ToolResult.model_validate(data)

    async def evidence_sample(self, store_id: str, request: dict[str, Any]) -> ToolResult:
        data = await self._call("POST", f"/stores/{_p(store_id)}/diagnostics/evidence-sample", body=request)
        return ToolResult.model_validate(data)

    async def cancellation_breakdown(self, store_id: str, request: dict[str, Any]) -> ToolResult:
        data = await self._call(
            "POST", f"/stores/{_p(store_id)}/diagnostics/cancellation-breakdown", body=request
        )
        return ToolResult.model_validate(data)

    async def fraud_signals(self, store_id: str, start: str, end: str) -> ToolResult:
        data = await self._call(
            "GET", f"/stores/{_p(store_id)}/diagnostics/fraud-signals", params={"start": start, "end": end}
        )
        return ToolResult.model_validate(data)

    async def resolve_evidence(self, store_id: str, evidence_ids: list[str]) -> EvidenceResolveResponse:
        """Checks the IDs in requests of at most RESOLVE_LIMIT. An ID Domain doesn't mention counts as invalid."""
        ids = list(dict.fromkeys(evidence_ids))
        valid: list[str] = []
        invalid: list[dict[str, Any]] = []
        for start in range(0, len(ids), RESOLVE_LIMIT):
            chunk = ids[start:start + RESOLVE_LIMIT]
            data = await self._call("POST", "/evidence/resolve", body={"store_id": store_id, "evidence_ids": chunk})
            part = EvidenceResolveResponse.model_validate(data)
            valid += part.valid
            invalid += part.invalid
        answered = set(valid) | {str(item.get("evidence_id")) for item in invalid}
        invalid += [{"evidence_id": e, "reason": "not_returned"} for e in ids if e not in answered]
        return EvidenceResolveResponse(valid=valid, invalid=invalid)

    async def create_proposal(self, case_id: str, body: ProposalCreate) -> Proposal:
        data = await self._call(
            "POST", f"/internal/cases/{_p(case_id)}/proposals", body=body.model_dump(mode="json"), internal=True
        )
        return Proposal.model_validate(data)

    async def report_investigation_status(self, case_id: str, body: InvestigationStatusUpdate) -> None:
        await self._call(
            "PUT", f"/internal/cases/{_p(case_id)}/investigation", body=body.model_dump(mode="json"), internal=True
        )


def _parse_error(response: httpx.Response) -> tuple[str, str, dict[str, Any]]:
    try:
        payload = response.json()
        err = payload.get("error", {}) if isinstance(payload, dict) else {}
        return (
            str(err.get("code") or f"HTTP_{response.status_code}"),
            str(err.get("message") or response.reason_phrase),
            err.get("details") if isinstance(err.get("details"), dict) else {},
        )
    except ValueError:
        return f"HTTP_{response.status_code}", response.reason_phrase, {}
