"""Database connection for the Domain service.

The connection string comes from the DATABASE_URL environment variable,
which is defined in the shared env template / docker-compose file.
Example: postgresql+psycopg://app:secret@postgres:5432/retail
"""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# TODO: confirm the variable name with the A-01 env template.
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/retail"
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
