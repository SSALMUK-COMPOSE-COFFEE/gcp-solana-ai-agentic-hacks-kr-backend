from fastapi import APIRouter, HTTPException
from sqlmodel import select

from app.core import chain, paysh, policy, settlement
from app.core.deps import ServiceToken, SessionDep
from app.models import (
    AgentDecision,
    AgentDecisionType,
    AgentRole,
    Campaign,
    CampaignStatus,
    Contribution,
    Micropay,
    Proof,
    Vendor,
)
from app.schemas.settlement import ReleaseRequest

router = APIRouter(prefix="/settlement", tags=["settlement"])

CAMPAIGN_NOT_FOUND = "존재하지 않는 캠페인입니다."
PROOF_NOT_FOUND = "존재하지 않는 증빙입니다."
REFUND_NOT_ALLOWED = "환불할 수 없는 상태입니다."


def _mask_wallet(address: str) -> str:
    return f"{address[:4]}…{address[-4:]}"


@router.post("/{campaign_id}/release")
async def release(
    campaign_id: int, body: ReleaseRequest, _: ServiceToken, session: SessionDep
) -> dict:
    campaign = await session.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail=CAMPAIGN_NOT_FOUND)

    proof = await session.get(Proof, body.proof_id)
    if proof is None or proof.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail=PROOF_NOT_FOUND)

    vendor = await session.get(Vendor, body.vendor_id)

    return await settlement.release(session, campaign, vendor, proof, body.amount)


@router.post("/{campaign_id}/refund")
async def refund(campaign_id: int, _: ServiceToken, session: SessionDep) -> dict:
    campaign = await session.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail=CAMPAIGN_NOT_FOUND)

    await settlement.lazy_close(session, campaign)
    await session.refresh(campaign, with_for_update=True)
    if campaign.status != CampaignStatus.REFUNDING:
        raise HTTPException(status_code=409, detail=REFUND_NOT_ALLOWED)

    result = await chain.post("/tx/refund-batch", {"campaignUuid": campaign.uuid})

    campaign.refunded_amount = int(result["refundedAmount"])
    campaign.refunded_count = result["refundedCount"]
    campaign.status = settlement.ONCHAIN_STATUS.get(result["status"], campaign.status)
    session.add(campaign)

    if result["pendingCount"] == 0:
        rows = await session.exec(
            select(Contribution).where(
                Contribution.campaign_id == campaign_id,
                Contribution.refunded == False,  # noqa: E712
            )
        )
        for row in rows.all():
            row.refunded = True
            session.add(row)

    session.add(
        AgentDecision(
            campaign_id=campaign.id,
            role=AgentRole.SETTLEMENT_REFUND,
            decision=AgentDecisionType.APPROVE,
            reasons=[
                f"환불 배치 실행 — 누적 {result['refundedCount']}명 · "
                f"{result['refundedAmount']} raw units, 잔여 {result['pendingCount']}건",
            ],
            model="onchain",
        )
    )
    await session.commit()

    return {
        "refundedCount": result["refundedCount"],
        "refundedAmount": int(result["refundedAmount"]),
        "pendingCount": result["pendingCount"],
        "txSignatures": result["signatures"],
        "status": campaign.status,
    }


@router.get("/{campaign_id}")
async def read_settlement(campaign_id: int, session: SessionDep) -> dict:
    campaign = await session.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail=CAMPAIGN_NOT_FOUND)

    receipts = await session.exec(
        select(Micropay)
        .where(Micropay.campaign_id == campaign_id, Micropay.paid == True)  # noqa: E712
        .order_by(Micropay.created_at.desc())
    )
    rows = list(receipts.all())
    await paysh.settle_x402(session, rows)

    return {
        "campaignId": campaign.id,
        "status": campaign.status,
        "raisedAmount": campaign.raised_amount,
        "releasedAmount": campaign.released_amount,
        "refundedAmount": campaign.refunded_amount,
        "remainingInEscrow": settlement.available_balance(campaign),
        "escrowPda": campaign.escrow_pda,
        "aiReviewBudget": (campaign.policy or {}).get("aiReviewBudget"),
        "aiReviewCost": await policy.ai_review_spent(session, campaign_id),
        "aiReceipts": [
            {
                "resource": row.resource,
                "rail": row.rail,
                "amount": row.amount,
                "authorized": row.authorized_amount,
                "settled": row.settled,
                "channelId": row.channel_id,
                "txSignature": row.tx_signature,
            }
            for row in rows
        ],
    }


@router.get("/{campaign_id}/breakdown")
async def read_breakdown(campaign_id: int, session: SessionDep) -> dict:
    campaign = await session.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail=CAMPAIGN_NOT_FOUND)

    result = await session.exec(
        select(Contribution)
        .where(Contribution.campaign_id == campaign_id)
        .order_by(Contribution.amount.desc())
    )
    total = campaign.raised_amount

    return {
        "breakdown": [
            {
                "userId": row.user_id,
                "walletAddress": _mask_wallet(row.wallet_address),
                "contributed": row.amount,
                "refunded": row.amount if row.refunded else 0,
                "ratio": round(row.amount / total, 6) if total else 0.0,
            }
            for row in result.all()
        ]
    }
