from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException

from app.core import chain
from app.models import Micropay

INSUFFICIENT = "잔액이 부족합니다."


async def micropay(
    session, resource: str, amount: int, campaign_id: int | None = None
) -> Micropay:
    record = Micropay(resource=resource, amount=amount, campaign_id=campaign_id)
    session.add(record)
    await session.flush()

    result = await chain.post(
        "/tx/micropay",
        {
            "idemKey": str(uuid5(NAMESPACE_URL, f"micropay:{record.id}")),
            "amount": str(amount),
        },
    )
    if not result.get("paid"):
        raise HTTPException(status_code=402, detail=INSUFFICIENT)

    record.paid = True
    record.tx_signature = result["signature"]
    session.add(record)
    return record
