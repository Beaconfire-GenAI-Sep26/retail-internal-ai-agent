"""JWT check and store scoping (architecture.md: every service checks the JWT itself).

The Auth service (A-02) issues HS256 tokens with these claims:
sub (user ID), name, role ("viewer" or "loe_analyst"), store_ids, iss, iat, exp.
"""
from dataclasses import dataclass

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.errors import ApiError
from app.settings import settings

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


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> CurrentUser:
    if creds is None or creds.scheme.lower() != "bearer" or not creds.credentials:
        raise ApiError(401, "UNAUTHENTICATED", "A Bearer token is required.")
    token = creds.credentials.strip()
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            issuer=settings.jwt_issuer,
            options={"require": ["sub", "exp", "iss"]},
        )
    except jwt.ExpiredSignatureError:
        raise ApiError(401, "UNAUTHENTICATED", "The token has expired.")
    except jwt.PyJWTError:
        raise ApiError(401, "UNAUTHENTICATED", "The token is not valid.")
    role = claims.get("role")
    store_ids = claims.get("store_ids")
    if role not in ROLES or not isinstance(store_ids, list):
        raise ApiError(401, "UNAUTHENTICATED", "The token is missing role or store_ids.")
    return CurrentUser(user_id=str(claims["sub"]), role=role, store_ids=frozenset(store_ids))


def require_analyst(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    if user.role != ANALYST:
        raise ApiError(403, "FORBIDDEN", "Only an LOE analyst can do this.")
    return user


def check_store(user: CurrentUser, store_id: str) -> None:
    """For store routes: a store outside the token's grants gets 403."""
    if not user.can_see(store_id):
        raise ApiError(403, "STORE_NOT_PERMITTED", f"Store {store_id} is not in your store grants.")
