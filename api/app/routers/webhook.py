import hashlib
import hmac

from fastapi import APIRouter, HTTPException, Request
from sqlmodel import select

from app.core.config import settings
from app.core.deps import SessionDep
from app.models import Micropay
from app.schemas.payment import PayshWebhookPayload

router = APIRouter(prefix="/webhook", tags=["webhook"])

SIGNATURE_INVALID = "서명 검증에 실패했습니다."


def _verify_signature(signature: str | None, payload: bytes) -> None:
    if not settings.webhook_secret or not signature:
        raise HTTPException(status_code=401, detail=SIGNATURE_INVALID)
    expected = hmac.new(settings.webhook_secret.encode(), payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail=SIGNATURE_INVALID)


@router.post("/paysh")
async def paysh_webhook(request: Request, session: SessionDep) -> dict:
    raw = await request.body()
    _verify_signature(request.headers.get("X-Signature"), raw)
    body = PayshWebhookPayload.model_validate_json(raw)

    result = await session.exec(
        select(Micropay).where(Micropay.tx_signature == body.tx_signature)
    )
    record = result.first()
    if record is not None and record.paid != body.paid:
        record.paid = body.paid
        session.add(record)
        await session.commit()

    return {"received": True}
