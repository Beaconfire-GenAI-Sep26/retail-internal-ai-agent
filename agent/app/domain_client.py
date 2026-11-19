"""Request-scoped Domain capability. Never store this client in graph state."""
import re

import httpx

from shared.security import APIError, JWTSettings, require_analyst, require_store, verify_token


async def domain_request(http, method, path, *, headers, json=None, params=None):
    try:
        response = await http.request(method, path.lstrip("/"), headers=headers,
                                      json=json, params=params, follow_redirects=False)
    except httpx.HTTPError:
        raise APIError(503, "UPSTREAM_UNAVAILABLE", "Domain service unavailable.") from None
    if response.is_success:
        return response.json()
    if response.status_code in {401, 403, 404, 409, 422}:
        try:
            error = response.json()["error"]
            raise APIError(response.status_code, error["code"], error["message"])
        except (ValueError, KeyError, TypeError):
            pass
    raise APIError(503, "UPSTREAM_UNAVAILABLE", "Domain service unavailable.")


class DomainClient:
    def __init__(self, http, *, access_token: str, settings: JWTSettings, store_id: str,
                 case_id: str, investigation_id: str, request_id: str, service_token: str):
        self.user = verify_token(access_token, settings)
        require_store(self.user, store_id)
        self.http, self.case_id, self.store_id = http, case_id, store_id
        self.investigation_id = investigation_id
        self._headers = {"Authorization": f"Bearer {access_token}", "X-Store-ID": store_id,
                         "X-Investigation-ID": investigation_id, "X-Request-ID": request_id}
        self._service_token = service_token

    async def request(self, method, path, *, json=None, params=None):
        # No absolute URLs, query strings, encoded separators or dot segments.
        # Restrict the capability to B-01 diagnostics and the agent's two writes.
        method = method.upper()
        allowed = False
        internal = False
        if re.fullmatch(r"/[A-Za-z0-9_/-]+", path) is None:
            raise APIError(403, "FORBIDDEN", "Domain path is not permitted.")
        if match := re.fullmatch(r"/stores/([^/]+)(.*)", path):
            if match[1] != self.store_id:
                raise APIError(403, "STORE_NOT_PERMITTED", "Call is outside this investigation's store.")
            suffix = match[2]
            allowed = method == "GET" and suffix in {"", "/menu", "/overview", "/diagnostics/events", "/diagnostics/fraud-signals"}
            allowed |= method == "POST" and suffix in {"/diagnostics/claim-breakdown", "/diagnostics/compare-periods", "/diagnostics/evidence-sample", "/diagnostics/cancellation-breakdown"}
        elif match := re.fullmatch(r"/(internal/)?cases/([^/]+)(.*)", path):
            if match[2] != self.case_id:
                raise APIError(403, "STORE_NOT_PERMITTED", "Call is outside this investigation's case.")
            if match[1]:
                internal = True
                require_analyst(self.user)
                allowed = (method, match[3]) in {("POST", "/proposals"), ("PUT", "/investigation")}
            else:
                allowed = method == "GET" and match[3] in {"", "/merchant-replies"}
        elif path == "/evidence/resolve":
            internal = True
            allowed = method == "POST" and isinstance(json, dict) and json.get("store_id") == self.store_id
        elif re.fullmatch(r"/(evidence|proposals)/[A-Z0-9-]+", path):
            # Domain independently resolves ownership and checks X-Store-ID.
            allowed = method == "GET"
        elif path == "/catalog/actions":
            allowed = method == "GET"
        if not allowed:
            raise APIError(403, "FORBIDDEN", "The Agent cannot perform this Domain operation.")
        if internal and isinstance(json, dict) and "investigation_id" in json and json["investigation_id"] != self.investigation_id:
            raise APIError(403, "FORBIDDEN", "Investigation context cannot be changed.")
        headers = dict(self._headers)
        if internal:
            headers["X-Service-Token"] = self._service_token
        return await domain_request(self.http, method, path, headers=headers, json=json, params=params)
