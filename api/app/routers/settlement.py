from fastapi import APIRouter, HTTPException

from app.core import settlement
from app.core.deps import ServiceToken, SessionDep
from app.models import Campaign, Proof, Vendor
from app.schemas.settlement import ReleaseRequest

router = APIRouter(prefix="/settlement", tags=["settlement"])

CAMPAIGN_NOT_FOUND = "존재하지 않는 캠페인입니다."
PROOF_NOT_FOUND = "존재하지 않는 증빙입니다."


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


@router.get("/{campaign_id}")
async def read_settlement(campaign_id: int, session: SessionDep) -> dict:
    campaign = await session.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail=CAMPAIGN_NOT_FOUND)

    return {
        "campaignId": campaign.id,
        "status": campaign.status,
        "raisedAmount": campaign.raised_amount,
        "releasedAmount": campaign.released_amount,
        "refundedAmount": campaign.refunded_amount,
        "remainingInEscrow": settlement.available_balance(campaign),
        "escrowPda": campaign.escrow_pda,
    }
