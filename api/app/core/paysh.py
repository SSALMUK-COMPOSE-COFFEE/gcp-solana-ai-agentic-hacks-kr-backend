from uuid import uuid4

from fastapi import HTTPException

from app.core import chain
from app.models import Micropay

INSUFFICIENT = "잔액이 부족합니다."


async def micropay(session, resource: str, amount: int) -> Micropay:
    result = await chain.post(
        "/tx/micropay", {"idemKey": str(uuid4()), "amount": str(amount)}
    )
    if not result.get("paid"):
        raise HTTPException(status_code=402, detail=INSUFFICIENT)

    record = Micropay(
        resource=resource,
        amount=amount,
        paid=True,
        tx_signature=result["signature"],
    )
    session.add(record)
    return record
