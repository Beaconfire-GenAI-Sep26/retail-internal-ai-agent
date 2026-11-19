import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.engine = create_engine(
        os.environ["DATABASE_URL"],
        pool_pre_ping=True,
        connect_args={"connect_timeout": 3},
    )
    try:
        yield
    finally:
        app.state.engine.dispose()


app = FastAPI(
    title="Retail Domain Service",
    version="0.1.0",
    root_path=os.getenv("ROOT_PATH", "/domain"),
    lifespan=lifespan,
)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "domain"}


@app.get("/ready", tags=["health"])
def ready(request: Request) -> JSONResponse:
    try:
        with request.app.state.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.warning("PostgreSQL readiness check failed")
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "service": "domain", "database": "unavailable"},
        )
    return JSONResponse(
        content={"status": "ok", "service": "domain", "database": "ok"},
    )
