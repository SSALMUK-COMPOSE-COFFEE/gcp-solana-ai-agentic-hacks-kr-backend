from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException

from app.core import chain
from app.models import Micropay, MicropayRail

INSUFFICIENT = "잔액이 부족합니다."


async def micropay(
    session, resource: str, amount: int, campaign_id: int | None = None
) -> Micropay:
    record = Micropay(
        resource=resource,
        amount=amount,
        campaign_id=campaign_id,
        rail=MicropayRail.PAYSH,
        settled=True,
    )
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


async def x402_receipt(
    session, resource: str, payment: dict, campaign_id: int | None = None
) -> Micropay:
    channel_id = payment.get("channelId")
    authorized = payment.get("authorized")
    if not channel_id or authorized is None:
        raise HTTPException(status_code=502, detail="x402 결제 정보가 불완전합니다.")

    record = Micropay(
        resource=resource,
        amount=0,
        campaign_id=campaign_id,
        rail=MicropayRail.X402,
        channel_id=channel_id,
        authorized_amount=int(authorized),
        paid=True,
        settled=False,
    )
    session.add(record)
    await session.flush()
    return record


async def settle_x402(session, rows: list[Micropay]) -> None:
    pending = [
        row
        for row in rows
        if row.rail == MicropayRail.X402 and not row.settled and row.channel_id
    ]
    if not pending:
        return

    changed = False
    for row in pending:
        try:
            result = await chain.get(f"/x402/channel/{row.channel_id}/settlement")
        except HTTPException:
            continue
        settled = result.get("settled")
        if settled is None:
            continue
        row.amount = int(settled)
        row.settled = True
        row.tx_signature = result.get("closeTx") or row.tx_signature
        session.add(row)
        changed = True

    if changed:
        await session.commit()
