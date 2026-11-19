"""Database connection for the Domain service.

The connection string comes from the DATABASE_URL environment variable,
which is defined in the root env template / Compose file. Structured POSTGRES_*
settings are also supported, using the same configuration as the Domain API.
Example: postgresql+psycopg://app:secret@postgres:5432/retail
"""
from sqlalchemy.orm import sessionmaker

from shared.database import database_engine

engine = database_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
