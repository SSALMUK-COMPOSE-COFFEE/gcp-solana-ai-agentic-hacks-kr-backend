from fastapi import APIRouter, HTTPException
from sqlmodel import select

from app.core import chain, paysh
from app.core.deps import CurrentUser, ServiceToken, SessionDep
from app.models import (
    Campaign,
    CampaignStatus,
    Contribution,
    Micropay,
    PaymentRequest,
    PaymentStatus,
    utcnow,
)
from app.schemas.payment import MicropayRequest, PaymentQrRequest, SolanaPayTxRequest

router = APIRouter(prefix="/payment", tags=["payment"])

CAMPAIGN_NOT_FOUND = "존재하지 않는 캠페인입니다."
CAMPAIGN_CLOSED = "이미 마감된 캠페인입니다."
REFERENCE_NOT_FOUND = "존재하지 않는 결제 요청입니다."


async def _open_campaign(session: SessionDep, campaign_id: int) -> Campaign:
    campaign = await session.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail=CAMPAIGN_NOT_FOUND)
    if campaign.status != CampaignStatus.FUNDING or campaign.deadline <= utcnow():
        raise HTTPException(status_code=409, detail=CAMPAIGN_CLOSED)
    return campaign


async def _payment_by_reference(session: SessionDep, reference: str) -> PaymentRequest:
    result = await session.exec(
        select(PaymentRequest).where(PaymentRequest.reference == reference)
    )
    payment = result.first()
    if payment is None:
        raise HTTPException(status_code=404, detail=REFERENCE_NOT_FOUND)
    return payment


async def _confirm(session: SessionDep, payment: PaymentRequest, signature: str) -> None:
    campaign = await session.get(Campaign, payment.campaign_id)

    result = await session.exec(
        select(Contribution).where(
            Contribution.campaign_id == payment.campaign_id,
            Contribution.wallet_address == payment.contributor_wallet,
        )
    )
    first_contribution = result.first() is None

    session.add(
        Contribution(
            campaign_id=payment.campaign_id,
            user_id=payment.user_id,
            wallet_address=payment.contributor_wallet,
            amount=payment.amount,
            reference=payment.reference,
            tx_signature=signature,
        )
    )

    campaign.raised_amount += payment.amount
    if first_contribution:
        campaign.contributor_count += 1

    payment.status = PaymentStatus.CONFIRMED
    payment.tx_signature = signature

    session.add_all([campaign, payment])
    await session.commit()


@router.post("/solana-pay/qr", status_code=201)
async def create_payment_request(
    body: PaymentQrRequest, user: CurrentUser, session: SessionDep
) -> dict:
    campaign = await _open_campaign(session, body.campaign_id)

    created = await chain.post("/pay/url", {})

    payment = PaymentRequest(
        reference=created["reference"],
        campaign_id=campaign.id,
        user_id=user.id,
        amount=body.amount,
    )
    session.add(payment)
    await session.commit()

    return {"reference": created["reference"], "url": created["url"]}


@router.get("/solana-pay/tx")
async def solana_pay_label() -> dict:
    return await chain.get("/pay/tx")


@router.post("/solana-pay/tx")
async def solana_pay_transaction(
    ref: str, body: SolanaPayTxRequest, session: SessionDep
) -> dict:
    payment = await _payment_by_reference(session, ref)
    campaign = await _open_campaign(session, payment.campaign_id)

    built = await chain.post(
        "/pay/tx",
        {
            "account": body.account,
            "campaignUuid": campaign.uuid,
            "amount": str(payment.amount),
            "reference": payment.reference,
        },
    )

    payment.contributor_wallet = body.account
    session.add(payment)
    await session.commit()

    return {"transaction": built["transaction"], "message": built["message"]}


@router.post("/paysh/micropay")
async def paysh_micropay(body: MicropayRequest, _: ServiceToken, session: SessionDep) -> dict:
    record = await paysh.micropay(session, body.resource, body.amount)
    await session.commit()

    return {"paid": True, "txSignature": record.tx_signature}


@router.get("/paysh/usage")
async def paysh_usage(_: CurrentUser, session: SessionDep) -> dict:
    result = await session.exec(select(Micropay).order_by(Micropay.created_at.desc()))
    rows = result.all()

    return {
        "totalSpent": sum(row.amount for row in rows if row.paid),
        "items": [
            {
                "resource": row.resource,
                "amount": row.amount,
                "paid": row.paid,
                "txSignature": row.tx_signature,
                "at": row.created_at,
            }
            for row in rows
        ],
    }


@router.get("/solana-pay/{ref}/status")
async def payment_status(ref: str, session: SessionDep) -> dict:
    payment = await _payment_by_reference(session, ref)

    if payment.status == PaymentStatus.PENDING and payment.contributor_wallet:
        result = await chain.get(f"/pay/reference/{ref}")
        if result["status"] == "confirmed":
            await _confirm(session, payment, result["txSignature"])

    return {
        "reference": payment.reference,
        "status": payment.status,
        "txSignature": payment.tx_signature,
    }
