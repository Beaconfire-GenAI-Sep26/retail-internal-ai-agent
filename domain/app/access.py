"""Authorization for the B-01 routes, independent of their business handlers.

Ownership is resolved from Domain storage, never from a caller-supplied store ID.
List/run handlers must use request.state.store_ids to scope their SQL queries.
"""
import hmac
import re

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from shared.security import APIError, authenticate, require_analyst, require_store
from shared.http import service_path, json_object

DIAGNOSTIC_POSTS = {"claim-breakdown", "compare-periods", "evidence-sample", "cancellation-breakdown"}


def require_service(request):
    expected = request.app.state.service_token
    supplied = request.headers.get("X-Service-Token", "")
    if not expected or not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise APIError(403, "SERVICE_TOKEN_INVALID", "A valid service token is required.")


class DomainAccess:
    def __init__(self, engine):
        self.engine = engine
        self.schema = "domain." if engine.dialect.name == "postgresql" else ""

    def owner(self, kind, resource_id):
        # The identifiers below are fixed server-owned SQL, never input interpolation.
        lookups = {
            "cases": ("cases", "case_id"),
            "proposals": ("proposals p JOIN {s}cases c ON p.case_id = c.case_id", "p.proposal_id"),
            "rechecks": ("rechecks r JOIN {s}cases c ON r.case_id = c.case_id", "r.recheck_id"),
            "EV-CLM": ("mi_claims", "evidence_id"),
            "EV-CXL": ("cancellations", "evidence_id"),
            "EV-EVT": ("operational_events", "evidence_id"),
            "EV-RPL": ("merchant_replies r JOIN {s}cases c ON r.case_id = c.case_id", "r.evidence_id"),
        }
        if kind not in lookups:
            raise APIError(404, "NOT_FOUND", "Resource not found.")
        table, key = lookups[kind]
        column = "c.store_id" if " JOIN " in table else "store_id"
        with self.engine.connect() as conn:
            store_id = conn.execute(text(f"SELECT {column} FROM {self.schema}{table.format(s=self.schema)} "
                                         f"WHERE {key} = :id"), {"id": resource_id}).scalar()
        if store_id is None:
            raise APIError(404, "CASE_NOT_FOUND" if kind == "cases" else "NOT_FOUND", "Resource not found.")
        return store_id

    async def authorize(self, request):
        user = authenticate(request, request.app.state.jwt)
        request.state.store_ids = tuple(user.store_ids)
        path, method = service_path(request), request.method
        store_id = None
        hide = method == "GET"

        if path.startswith("/internal/"):
            require_service(request)
            require_analyst(user)
            if not request.headers.get("X-Investigation-ID") or not request.headers.get("X-Store-ID"):
                raise APIError(403, "FORBIDDEN", "Internal calls require investigation and store context.")
            match = re.fullmatch(r"/internal/cases/([^/]+)/(proposals|investigation)", path)
            if not match or (method, match[2]) not in {("POST", "proposals"), ("PUT", "investigation")}:
                raise APIError(403, "FORBIDDEN", "Internal operation is not permitted.")
            store_id = await self.lookup("cases", match[1])
        elif path == "/cases" and method == "GET":
            # List queries always intersect the optional filter with grants.
            pass
        elif path == "/catalog/actions" and method == "GET":
            pass
        elif path == "/monitor/run" and method == "POST":
            require_analyst(user)
        elif path == "/evidence/resolve" and method == "POST":
            require_service(request)
            body = await json_object(request)
            store_id = body.get("store_id")
            if not isinstance(store_id, str):
                raise APIError(422, "VALIDATION_ERROR", "store_id is required.")
        elif match := re.fullmatch(r"/stores/([^/]+)(.*)", path):
            store_id, suffix = match[1], match[2]
            allowed = (method == "GET" and suffix in {"", "/menu", "/overview", "/diagnostics/events", "/diagnostics/fraud-signals"})
            allowed |= method == "POST" and suffix.removeprefix("/diagnostics/") in DIAGNOSTIC_POSTS and suffix.startswith("/diagnostics/")
            if not allowed:
                raise APIError(403, "FORBIDDEN", "Operation is not permitted.")
            hide = False
        elif match := re.fullmatch(r"/(cases|proposals|rechecks|evidence)/([^/]+)(.*)", path):
            kind, resource_id, suffix = match.groups()
            readable = method == "GET" and (suffix == "" or kind == "cases" and suffix in {"/audit", "/merchant-replies", "/rechecks"})
            writable = method == "POST" and ((kind == "proposals" and suffix in {"/versions", "/decision", "/merchant-reply"}) or (kind == "rechecks" and suffix == "/run"))
            if not readable and not writable:
                raise APIError(403, "FORBIDDEN", "Operation is not permitted.")
            if writable:
                require_analyst(user)
            store_id = await self.lookup(resource_id.rsplit("-", 1)[0] if kind == "evidence" else kind, resource_id)
        else:
            raise APIError(403, "FORBIDDEN", "Operation has no access policy.")

        # X-Store-ID only narrows grants. Spoofed identity/role headers are ignored.
        context = request.headers.get("X-Store-ID")
        if context:
            require_store(user, context)
            request.state.store_ids = (context,)
            if store_id is not None and context != store_id:
                raise APIError(403, "STORE_NOT_PERMITTED", "The requested resource is outside the call's store context.")
        if store_id is not None:
            require_store(user, store_id, hide=hide)
            request.state.store_id = store_id

    async def lookup(self, kind, resource_id):
        try:
            return await run_in_threadpool(self.owner, kind, resource_id)
        except SQLAlchemyError:
            raise APIError(503, "UPSTREAM_UNAVAILABLE", "Domain storage unavailable.") from None
