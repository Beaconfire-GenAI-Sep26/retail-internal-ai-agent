"""Service settings, read from the environment and agent/.env (see .env.example)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

AGENT_ROOT = Path(__file__).resolve().parent.parent

Effort = Literal["low", "medium", "high", "xhigh", "max"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(AGENT_ROOT / ".env"), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["local", "ci", "demo"] = "local"
    log_level: str = "info"

    # Auth. JWT_SECRET must match the Auth Service; set it in .env.
    jwt_secret: str = ""
    jwt_issuer: str = "mi-auth"

    # Domain Service
    agent_domain_mode: Literal["http", "fixtures"] = "http"
    domain_service_url: str = "http://domain:8000"
    internal_service_token: str = ""
    agent_fixtures_dir: Path = AGENT_ROOT / "tests" / "fixtures" / "domain"
    domain_timeout_seconds: float = 10.0

    # Claude API. ANTHROPIC_API_KEY is read from .env.
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5-5"
    agent_effort: Effort = "medium"
    agent_speed: Literal["standard", "fast"] = "standard"

    # Investigation bounds
    agent_max_steps: int = 12
    agent_max_retries: int = 2
    agent_run_timeout_seconds: int = 1200
    agent_max_questions: int = 0
    agent_max_reason_calls: int | None = None  # default: 2 * AGENT_MAX_STEPS + 4

    # Persistence. postgres keeps checkpoints in the agent schema, so a paused run survives a restart.
    agent_checkpointer: Literal["memory", "postgres"] = "memory"
    database_url: str = ""
    # Used when DATABASE_URL is empty, the way Compose configures every service (role agent_svc).
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = ""
    postgres_user: str = ""
    postgres_password: str = ""

    # Tracing (M2). Empty keys turn tracing off.
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_base_url: str = "https://cloud.langfuse.com"

    @property
    def max_reason_calls(self) -> int:
        return self.agent_max_reason_calls or 2 * self.agent_max_steps + 4

    @property
    def recursion_limit(self) -> int:
        return 5 * self.max_reason_calls + 10

    @property
    def psycopg_url(self) -> str:
        """DATABASE_URL in the form psycopg and libpq accept (no SQLAlchemy driver suffix)."""
        return self.database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
