"""Minimal JWT check per architecture.md: HS256, JWT_SECRET, JWT_ISSUER, role and store grants.

A-02 may replace this with shared code. The token itself is only ever passed on to Domain.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import jwt
from fastapi import Request

from app.config import Settings
from app.errors import INTERNAL, UNAUTHENTICATED, AppError
from app.logs import log_event

logger = logging.getLogger("agent.auth")
ROLES = ("viewer", "loe_analyst")


@dataclass(frozen=True)
class Principal:
    user_id: str
    name: str
    role: str
    store_ids: frozenset[str]
    expires_at: int
    token: str

    @property
    def is_analyst(self) -> bool:
        return self.role == "loe_analyst"

    def can_see(self, store_id: str) -> bool:
        return store_id in self.store_ids


def verify_token(token: str, settings: Settings) -> Principal:
    if not settings.jwt_secret:
        log_event(logger, logging.ERROR, "JWT_SECRET is not configured")
        raise AppError(500, INTERNAL, "The service is missing its JWT configuration.")
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "sub", "iss"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AppError(401, UNAUTHENTICATED, "The token has expired. Log in again.") from exc
    except jwt.InvalidTokenError as exc:
        raise AppError(401, UNAUTHENTICATED, "The token is missing, malformed or invalid.") from exc
    role = claims.get("role")
    if role not in ROLES:
        raise AppError(403, "FORBIDDEN", "The token's role can't use the Agent Service.")
    stores = claims.get("store_ids") or []
    if not isinstance(stores, list):
        raise AppError(401, UNAUTHENTICATED, "The token's store_ids claim is malformed.")
    return Principal(
        user_id=str(claims["sub"]),
        name=str(claims.get("name", "")),
        role=role,
        store_ids=frozenset(str(s) for s in stores),
        expires_at=int(claims["exp"]),
        token=token,
    )


async def get_principal(request: Request) -> Principal:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AppError(401, UNAUTHENTICATED, "Send the user's JWT as Authorization: Bearer <token>.")
    return verify_token(token.strip(), request.app.state.settings)
