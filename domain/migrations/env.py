"""Alembic environment for the Domain service.

- Connection settings come from app/db.py (DATABASE_URL or POSTGRES_* variables).
- Only the `domain` and `eval` schemas belong to this service; other schemas
  in the shared database (auth, agent checkpoints) are ignored.
- Alembic's own version table lives in `domain`, so it never clashes with
  another service's Alembic.
"""
from alembic import context
from sqlalchemy import text

from domain.app.db import engine
from domain.app.models import DOMAIN_SCHEMA, EVAL_SCHEMA, Base

OWNED_SCHEMAS = {DOMAIN_SCHEMA, EVAL_SCHEMA}
target_metadata = Base.metadata


def include_name(name, type_, parent_names):
    # Only compare schemas this service owns.
    if type_ == "schema":
        return name in OWNED_SCHEMAS
    return True


def run_migrations_online() -> None:
    with engine.connect() as connection:
        # The version table is created before the first migration runs,
        # so the schemas must exist first.
        for schema in sorted(OWNED_SCHEMAS):
            connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        connection.commit()

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_name=include_name,
            version_table_schema=DOMAIN_SCHEMA,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("Offline mode is not supported; run against a database.")
run_migrations_online()
