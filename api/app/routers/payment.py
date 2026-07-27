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
    RewardTier,
    utcnow,
)
from app.schemas.payment import (
    ContributeRequest,
    MicropayRequest,
    PaymentQrRequest,
    SolanaPayTxRequest,
)

router = APIRouter(prefix="/payment", tags=["payment"])

CAMPAIGN_NOT_FOUND = "존재하지 않는 캠페인입니다."
CAMPAIGN_CLOSED = "이미 마감된 캠페인입니다."
REFERENCE_NOT_FOUND = "존재하지 않는 결제 요청입니다."
TIER_NOT_FOUND = "존재하지 않는 티어입니다."
TIER_SOLD_OUT = "품절된 티어입니다."
AMOUNT_REQUIRED = "금액 또는 티어를 지정해야 합니다."
TX_VERIFY_FAILED = "트랜잭션 검증에 실패했습니다."
ALREADY_PROCESSED = "이미 처리된 트랜잭션입니다."


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
            tier_id=payment.tier_id,
            wallet_address=payment.contributor_wallet,
            amount=payment.amount,
            reference=payment.reference,
            tx_signature=signature,
        )
    )

    campaign.raised_amount += payment.amount
    if first_contribution:
        campaign.contributor_count += 1

    if payment.tier_id is not None:
        tier = await session.get(RewardTier, payment.tier_id)
        if tier is not None:
            tier.sold_count += 1
            session.add(tier)

    payment.status = PaymentStatus.CONFIRMED
    payment.tx_signature = signature

    session.add_all([campaign, payment])
    await session.commit()


@router.post("/solana-pay/qr", status_code=201)
async def create_payment_request(
    body: PaymentQrRequest, user: CurrentUser, session: SessionDep
) -> dict:
    campaign = await _open_campaign(session, body.campaign_id)

    amount = body.amount
    if body.tier_id is not None:
        tier = await session.get(RewardTier, body.tier_id)
        if tier is None or tier.campaign_id != campaign.id:
            raise HTTPException(status_code=400, detail=TIER_NOT_FOUND)
        if tier.limit is not None and tier.sold_count >= tier.limit:
            raise HTTPException(status_code=409, detail=TIER_SOLD_OUT)
        amount = tier.price
    if amount is None:
        raise HTTPException(status_code=400, detail=AMOUNT_REQUIRED)

    created = await chain.post("/pay/url", {})

    payment = PaymentRequest(
        reference=created["reference"],
        campaign_id=campaign.id,
        user_id=user.id,
        tier_id=body.tier_id,
        amount=amount,
    )
    session.add(payment)
    await session.commit()

    return {"reference": created["reference"], "url": created["url"], "amount": amount}


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


@router.post("/contribute", status_code=201)
async def contribute(body: ContributeRequest, _: CurrentUser, session: SessionDep) -> dict:
    payment = await _payment_by_reference(session, body.reference)

    if payment.status == PaymentStatus.CONFIRMED:
        raise HTTPException(status_code=409, detail=ALREADY_PROCESSED)
    if not payment.contributor_wallet:
        raise HTTPException(status_code=400, detail=TX_VERIFY_FAILED)

    result = await chain.get(f"/pay/reference/{body.reference}")
    if result["status"] != "confirmed" or result["txSignature"] != body.tx_signature:
        raise HTTPException(status_code=400, detail=TX_VERIFY_FAILED)

    await _confirm(session, payment, body.tx_signature)

    contribution = await session.exec(
        select(Contribution).where(Contribution.reference == body.reference)
    )
    record = contribution.first()

    return {"contributionId": record.id, "amount": payment.amount}


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
