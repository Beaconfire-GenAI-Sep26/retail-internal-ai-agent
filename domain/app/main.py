"""Domain service: cases, store data, read-only diagnostics and the store monitor (C-02)."""
import os

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.db import engine
from app.errors import install_error_handlers
from app.routers import cases, evidence, monitor, stores

app = FastAPI(
    title="Domain Service",
    description="Cases, store data, read-only diagnostic tools and the fixed-rule store monitor.",
    root_path=os.environ.get("ROOT_PATH", ""),
)
install_error_handlers(app)
app.include_router(cases.router)
app.include_router(stores.router)
app.include_router(monitor.router)
app.include_router(evidence.router)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}


@app.get("/ready", tags=["health"])
def ready():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content={"status": "not_ready"})
    return {"status": "ready"}
