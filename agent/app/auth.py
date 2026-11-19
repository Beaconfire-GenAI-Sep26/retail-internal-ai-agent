"""Minimal JWT check per architecture.md: HS256, JWT_SECRET, JWT_ISSUER, role and store grants.

A-02 may replace this with shared code. The token itself is only ever passed on to Domain.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import jwt
from fastapi import Request

from shared.security import APIError, JWTSettings, verify_token as verify_user_token
from agent.app.config import Settings
from agent.app.errors import INTERNAL, UNAUTHENTICATED, AppError
from agent.app.logs import log_event

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
    try:
        user = verify_user_token(token, JWTSettings(settings.jwt_secret, settings.jwt_issuer))
    except APIError as exc:
        raise AppError(exc.status, exc.code, exc.message) from None
    claims = jwt.decode(token, options={"verify_signature": False})
    return Principal(user_id=user.user_id, name=user.display_name, role=user.role,
                     store_ids=frozenset(user.store_ids), expires_at=claims["exp"], token=token)


async def get_principal(request: Request) -> Principal:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AppError(401, UNAUTHENTICATED, "Send the user's JWT as Authorization: Bearer <token>.")
    return verify_token(token.strip(), request.app.state.settings)
