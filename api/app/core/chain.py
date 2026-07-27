import httpx
from fastapi import HTTPException

from app.core.config import settings

DISABLED = "온체인 서비스가 비활성화되어 있습니다."
UNAVAILABLE = "온체인 처리에 실패했습니다. 잠시 후 다시 시도해 주세요."


async def post(path: str, payload: dict) -> dict:
    if not settings.chain_enabled:
        raise HTTPException(status_code=503, detail=DISABLED)

    try:
        async with httpx.AsyncClient(timeout=settings.chain_svc_timeout) as client:
            response = await client.post(f"{settings.chain_svc_url}{path}", json=payload)
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail=UNAVAILABLE) from None

    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=UNAVAILABLE)

    return response.json()
