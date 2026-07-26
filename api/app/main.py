import os

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse

APP_VERSION = os.environ.get("APP_VERSION", "0.1.0")
CHAIN_SVC_URL = os.environ.get("CHAIN_SVC_URL", "http://localhost:8081")
DATABASE_URL = os.environ.get("DATABASE_URL", "")

app = FastAPI(title="팬덤 총대 에이전트 API", version=APP_VERSION)


@app.get("/health")
async def health() -> JSONResponse:
    db_status = "down"
    chain_status = "down"

    if DATABASE_URL:
        db_status = "up"

    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{CHAIN_SVC_URL}/health")
            if r.status_code == 200:
                chain_status = "up"
    except httpx.HTTPError:
        pass

    ok = db_status == "up" and chain_status == "up"
    body = {
        "status": "ok" if ok else "degraded",
        "version": APP_VERSION,
        "db": db_status,
        "chainSvc": chain_status,
    }
    return JSONResponse(body, status_code=200 if ok else 503)


