import os

from fastapi import FastAPI

app = FastAPI(
    title="Retail Auth Service",
    version="0.1.0",
    root_path=os.getenv("ROOT_PATH", "/auth"),
)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "auth"}
