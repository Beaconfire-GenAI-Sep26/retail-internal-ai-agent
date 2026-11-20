"""JWT check and store scoping (architecture.md: every service checks the JWT itself).

The Auth service (A-02) issues HS256 tokens with these claims:
sub (user ID), name, role ("viewer" or "loe_analyst"), store_ids, iss, iat, exp.
"""
from dataclasses import dataclass

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from domain.app.errors import ApiError
from shared.security import authenticate

ANALYST = "loe_analyst"
ROLES = {"viewer", ANALYST}


@dataclass(frozen=True)
class CurrentUser:
    user_id: str
    role: str
    store_ids: frozenset[str]

    def can_see(self, store_id: str) -> bool:
        return store_id in self.store_ids


# auto_error=False so a missing token gets our error envelope, not FastAPI's default 403.
# HTTPBearer also adds the "Authorize" button to the /docs page.
bearer = HTTPBearer(auto_error=False, description="JWT from the Auth service (or scripts/make_demo_token.py)")


def current_user(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> CurrentUser:
    # The shared middleware verifies every claim before routing. Return its
    # narrowed store context so C-02 query helpers enforce X-Store-ID too.
    user = getattr(request.state, "user", None)
    if user is None:
        user = authenticate(request, request.app.state.jwt)
    stores = getattr(request.state, "store_ids", user.store_ids)
    return CurrentUser(user_id=user.user_id, role=user.role, store_ids=frozenset(stores))


def require_analyst(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    if user.role != ANALYST:
        raise ApiError(403, "FORBIDDEN", "Only an LOE analyst can do this.")
    return user


def check_store(user: CurrentUser, store_id: str) -> None:
    """For store routes: a store outside the token's grants gets 403."""
    if not user.can_see(store_id):
        raise ApiError(403, "STORE_NOT_PERMITTED", f"Store {store_id} is not in your store grants.")
