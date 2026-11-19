import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

import jwt
from fastapi import Request
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

ROLE = Literal["viewer", "loe_analyst"]
STORE_ID = re.compile(r"STORE-[A-Z]\Z")


class APIError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def unauthenticated() -> APIError:
    return APIError(401, "UNAUTHENTICATED", "Credentials are missing, invalid or expired.")


class User(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    user_id: str
    display_name: str
    role: ROLE
    store_ids: list[str]

    @field_validator("user_id")
    @classmethod
    def valid_user_id(cls, value):
        if not re.fullmatch(r"USR-\d{3,}", value):
            raise ValueError("Invalid user ID")
        return value

    @field_validator("store_ids")
    @classmethod
    def valid_stores(cls, values):
        if any(not STORE_ID.fullmatch(value) for value in values) or len(set(values)) != len(values):
            raise ValueError("Invalid store grants")
        return values


@dataclass(frozen=True)
class JWTSettings:
    secret: str
    issuer: str = "mi-auth"
    ttl_minutes: int = 60

    def __post_init__(self):
        if len(self.secret.encode()) < 32:
            raise ValueError("JWT_SECRET must contain at least 32 bytes")
        if not self.issuer or self.ttl_minutes <= 0:
            raise ValueError("JWT issuer and token lifetime must be configured")

    @classmethod
    def from_env(cls):
        return cls(os.environ["JWT_SECRET"], os.getenv("JWT_ISSUER", "mi-auth"),
                   int(os.getenv("JWT_TTL_MINUTES", "60")))


def issue_token(user: User, settings: JWTSettings) -> dict:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    expires = now + timedelta(minutes=settings.ttl_minutes)
    token = jwt.encode({
        "sub": user.user_id, "name": user.display_name, "role": user.role,
        "store_ids": user.store_ids, "iss": settings.issuer,
        "iat": int(now.timestamp()), "exp": int(expires.timestamp()),
    }, settings.secret, algorithm="HS256")
    return {"access_token": token, "token_type": "bearer",
            "expires_at": expires.isoformat().replace("+00:00", "Z"), "user": user.model_dump()}


def verify_token(token: str, settings: JWTSettings) -> User:
    try:
        claims = jwt.decode(token, settings.secret, algorithms=["HS256"], issuer=settings.issuer,
                            options={"require": ["sub", "name", "role", "store_ids", "iss", "iat", "exp"]})
        # PyJWT accepts numeric strings; the contract requires integer NumericDates.
        if any(type(claims[key]) is not int for key in ("iat", "exp")):
            raise ValueError("Invalid NumericDate")
        if claims["exp"] <= claims["iat"]:
            raise ValueError("Invalid lifetime")
        return User(user_id=claims["sub"], display_name=claims["name"],
                    role=claims["role"], store_ids=claims["store_ids"])
    except (jwt.InvalidTokenError, ValidationError, ValueError, TypeError, KeyError):
        raise unauthenticated() from None


def authenticate(request: Request, settings: JWTSettings) -> User:
    headers = request.headers.getlist("authorization")
    if len(headers) != 1:
        raise unauthenticated()
    parts = headers[0].split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise unauthenticated()
    user = verify_token(parts[1], settings)
    request.state.user = user
    # Request-scoped only. Never put this in a graph checkpoint or logs.
    request.state.access_token = parts[1]
    return user


def require_analyst(user: User):
    if user.role != "loe_analyst":
        raise APIError(403, "FORBIDDEN", "This action requires the LOE Analyst role.")


def require_store(user: User, store_id: str, *, hide: bool = False):
    if store_id not in user.store_ids:
        if hide:
            raise APIError(404, "NOT_FOUND", "Resource not found.")
        raise APIError(403, "STORE_NOT_PERMITTED", "You do not have access to this store.")
