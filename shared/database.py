import os

from sqlalchemy import create_engine
from sqlalchemy.engine import URL, make_url


def database_engine(env_name="DATABASE_URL"):
    url = os.getenv(env_name)
    if not url:
        url = URL.create("postgresql+psycopg", username=os.environ["POSTGRES_USER"],
                         password=os.environ["POSTGRES_PASSWORD"],
                         host=os.getenv("POSTGRES_HOST", "postgres"),
                         port=int(os.getenv("POSTGRES_PORT", "5432")),
                         database=os.environ["POSTGRES_DB"])
    connect_args = {"connect_timeout": 3} if make_url(url).get_backend_name() == "postgresql" else {}
    return create_engine(url, pool_pre_ping=True, connect_args=connect_args)
