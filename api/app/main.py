from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import settings
from app.core.db import async_session, init_db
from app.core.errors import register_error_handlers
from app.routers import agent, auth, campaign, payment, settlement, users, vendor, webhook


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    yield


app = FastAPI(title="팬덤 총대 에이전트 API", version=settings.app_version, lifespan=lifespan)

register_error_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(campaign.router)
app.include_router(payment.router)
app.include_router(users.router)
app.include_router(vendor.router)
app.include_router(settlement.router)
app.include_router(agent.router)
app.include_router(webhook.router)


async def _check_db() -> str:
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        return "up"
    except Exception:
        return "down"


async def _check_chain_svc() -> str:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{settings.chain_svc_url}/health")
            return "up" if r.status_code == 200 else "down"
    except httpx.HTTPError:
        return "down"


@app.get("/health")
async def health() -> JSONResponse:
    db_status = await _check_db()
    chain_status = await _check_chain_svc()
    ok = db_status == "up" and chain_status == "up"
    body = {
        "status": "ok" if ok else "degraded",
        "version": settings.app_version,
        "db": db_status,
        "chainSvc": chain_status,
    }
    return JSONResponse(body, status_code=200 if ok else 503)
