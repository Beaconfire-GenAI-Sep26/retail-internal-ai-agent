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

from app.contracts.models import (
    ActionCatalogEntry,
    CaseDetail,
    EvidenceResolveResponse,
    InvestigationStatusUpdate,
    MenuItem,
    Proposal,
    ProposalCreate,
    ToolResult,
)
from app.logs import log_event

logger = logging.getLogger("agent.domain")


class DomainError(Exception):
    """A Domain call failed. `status` is the HTTP status, or 503 when Domain was unreachable."""

    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(f"{status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}

    @property
    def unavailable(self) -> bool:
        return self.status >= 500

    @property
    def rejected(self) -> bool:
        return self.status == 422


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
    def bind(self, *, token: str, request_id: str, investigation_id: str | None) -> DomainPort: ...
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
    ):
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout, transport=transport)
        self._service_token = service_token
        self._max_retries = max_retries
        self._backoff = backoff_seconds

    def bind(self, *, token: str, request_id: str, investigation_id: str | None) -> DomainPort:
        return _BoundHttpDomain(self, token=token, request_id=request_id, investigation_id=investigation_id)

    async def aclose(self) -> None:
        await self._client.aclose()


class _BoundHttpDomain:
    def __init__(self, owner: HttpDomainClient, *, token: str, request_id: str, investigation_id: str | None):
        self._owner = owner
        self._token = token
        self._request_id = request_id
        self._investigation_id = investigation_id

    async def _call(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: Any = None,
        internal: bool = False,
    ) -> Any:
        headers = {"Authorization": f"Bearer {self._token}", "X-Request-ID": self._request_id}
        if self._investigation_id:
            headers["X-Investigation-ID"] = self._investigation_id
        if internal:
            headers["X-Service-Token"] = self._owner._service_token
        owner = self._owner
        response: httpx.Response | None = None
        failure = ""
        for attempt in range(owner._max_retries + 1):
            if attempt:
                await asyncio.sleep(owner._backoff * 2 ** (attempt - 1))
            try:
                response = await owner._client.request(method, path, params=params, json=body, headers=headers)
            except httpx.HTTPError as exc:
                failure = f"{type(exc).__name__} calling {method} {path}"
                response = None
                continue
            if response.status_code >= 500:
                failure = f"Domain returned {response.status_code} for {method} {path}"
                continue
            break
        if response is None or response.status_code >= 500:
            log_event(logger, logging.WARNING, "domain unavailable", method=method, path=path, reason=failure)
            raise DomainError(503, "UPSTREAM_UNAVAILABLE", failure or "Domain is unavailable.")
        if response.status_code >= 400:
            code, message, details = _parse_error(response)
            raise DomainError(response.status_code, code, message, details)
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    async def get_case(self, case_id: str) -> CaseDetail:
        return CaseDetail.model_validate(await self._call("GET", f"/cases/{_p(case_id)}"))

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
        data = await self._call("POST", "/evidence/resolve", body={"store_id": store_id, "evidence_ids": evidence_ids})
        return EvidenceResolveResponse.model_validate(data)

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
