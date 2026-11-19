"""Auth-owned accounts and one-use refresh tokens. Raw refresh tokens are never stored."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time

from sqlalchemy import (JSON, Boolean, Column, ForeignKey, Integer, MetaData, String,
                        Table, insert, select, update)
from sqlalchemy.schema import CreateSchema

from shared.security import APIError, User, unauthenticated

metadata = MetaData(schema="auth")
users = Table("users", metadata,
              Column("user_id", String(20), primary_key=True),
              Column("username", String(80), unique=True, nullable=False),
              Column("display_name", String(120), nullable=False),
              Column("password_hash", String(256), nullable=False),
              Column("role", String(32), nullable=False),
              Column("store_ids", JSON, nullable=False),
              Column("active", Boolean, nullable=False, default=True))
sessions = Table("refresh_sessions", metadata,
                 Column("token_hash", String(64), primary_key=True),
                 Column("family_id", String(64), nullable=False, index=True),
                 Column("user_id", ForeignKey("auth.users.user_id"), nullable=False),
                 Column("expires_at", Integer, nullable=False),
                 Column("consumed", Boolean, nullable=False, default=False),
                 Column("revoked", Boolean, nullable=False, default=False))


def password_hash(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    return f"scrypt${salt}${digest.hex()}"


def password_matches(password: str, encoded: str) -> bool:
    _, salt, _ = encoded.split("$")
    return hmac.compare_digest(password_hash(password, salt), encoded)


def profile(row) -> User:
    return User(user_id=row["user_id"], display_name=row["display_name"],
                role=row["role"], store_ids=row["store_ids"])


def digest_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class AuthRepository:
    def __init__(self, engine):
        self.engine = engine.execution_options(schema_translate_map={"auth": None}) \
            if engine.dialect.name == "sqlite" else engine
        self.dummy_hash = password_hash(secrets.token_urlsafe(32))

    def initialize(self):
        with self.engine.begin() as conn:
            if conn.dialect.name == "postgresql":
                conn.execute(CreateSchema("auth", if_not_exists=True))
            metadata.create_all(conn)

    def seed(self, analyst_password: str, viewer_password: str):
        accounts = [("USR-001", "analyst", "Demo LOE Analyst", "loe_analyst", ["STORE-A", "STORE-B"], analyst_password),
                    ("USR-002", "viewer", "Demo Viewer", "viewer", ["STORE-A"], viewer_password)]
        with self.engine.begin() as conn:
            for user_id, username, name, role, stores, password in accounts:
                if len(password) < 12:
                    raise ValueError("Seed account passwords must contain at least 12 characters")
                if conn.execute(select(users.c.user_id).where(users.c.username == username)).first():
                    continue
                conn.execute(insert(users).values(user_id=user_id, username=username, display_name=name,
                             password_hash=password_hash(password), role=role, store_ids=stores, active=True))

    def login(self, username: str, password: str) -> User:
        with self.engine.connect() as conn:
            row = conn.execute(select(users).where(users.c.username == username)).mappings().first()
        valid = password_matches(password, row["password_hash"] if row else self.dummy_hash)
        if not row or not valid or not row["active"]:
            raise APIError(401, "INVALID_CREDENTIALS", "Invalid username or password.")
        return profile(row)

    def current_user(self, user_id: str) -> User:
        with self.engine.connect() as conn:
            row = conn.execute(select(users).where(users.c.user_id == user_id,
                                                   users.c.active.is_(True))).mappings().first()
        if not row:
            raise unauthenticated()
        return profile(row)

    def create_session(self, user: User, ttl_days: int) -> tuple[str, int]:
        raw = secrets.token_urlsafe(48)
        expires = int(time.time()) + ttl_days * 86400
        with self.engine.begin() as conn:
            conn.execute(insert(sessions).values(token_hash=digest_token(raw), family_id=secrets.token_hex(32),
                         user_id=user.user_id, expires_at=expires, consumed=False, revoked=False))
        return raw, expires

    def rotate(self, raw: str) -> tuple[User, str, int]:
        replacement = secrets.token_urlsafe(48)
        result = None
        with self.engine.begin() as conn:
            row = conn.execute(select(sessions).where(sessions.c.token_hash == digest_token(raw))
                               .with_for_update()).mappings().first()
            if row and row["consumed"]:
                conn.execute(update(sessions).where(sessions.c.family_id == row["family_id"]).values(revoked=True))
            elif row and not row["revoked"] and row["expires_at"] > int(time.time()):
                account = conn.execute(select(users).where(users.c.user_id == row["user_id"],
                                                           users.c.active.is_(True))).mappings().first()
                claimed = conn.execute(update(sessions).where(sessions.c.token_hash == row["token_hash"],
                                      sessions.c.consumed.is_(False), sessions.c.revoked.is_(False))
                                       .values(consumed=True)).rowcount
                if account and claimed == 1:
                    conn.execute(insert(sessions).values(token_hash=digest_token(replacement),
                                 family_id=row["family_id"], user_id=row["user_id"], expires_at=row["expires_at"],
                                 consumed=False, revoked=False))
                    result = profile(account), replacement, row["expires_at"]
        # Raise after commit so replay revocations survive the rejected request.
        if result is None:
            raise unauthenticated()
        return result

    def revoke(self, raw: str | None):
        if not raw:
            return
        with self.engine.begin() as conn:
            row = conn.execute(select(sessions.c.family_id).where(sessions.c.token_hash == digest_token(raw))).first()
            if row:
                conn.execute(update(sessions).where(sessions.c.family_id == row[0]).values(revoked=True))
