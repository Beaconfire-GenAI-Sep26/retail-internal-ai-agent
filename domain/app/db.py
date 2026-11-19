"""Database connection for the Domain service.

Two ways to configure the connection, checked in this order:

1. DATABASE_URL, as described in architecture.md (B-01), e.g.
   postgresql+psycopg://user:password@postgres:5432/retail_agent
2. The separate POSTGRES_* variables that the A-01 docker-compose file passes
   to the domain service: POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB,
   POSTGRES_USER and POSTGRES_PASSWORD.

If neither is set, it falls back to the local test database from README.md.
"""
import os

from sqlalchemy import URL, create_engine
from sqlalchemy.orm import sessionmaker

LOCAL_DEFAULT_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/retail"


def database_url() -> str | URL:
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    if os.environ.get("POSTGRES_USER"):
        return URL.create(
            drivername="postgresql+psycopg",
            username=os.environ["POSTGRES_USER"],
            password=os.environ.get("POSTGRES_PASSWORD"),
            host=os.environ.get("POSTGRES_HOST", "postgres"),
            port=int(os.environ.get("POSTGRES_PORT", "5432")),
            database=os.environ.get("POSTGRES_DB"),
        )
    return LOCAL_DEFAULT_URL


engine = create_engine(database_url(), pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
