from datetime import timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from app.core import chain, settlement
from app.core.deps import CurrentUser, SessionDep
from app.models import Campaign, CampaignStatus, utcnow
from app.schemas.campaign import CreateCampaignRequest

router = APIRouter(prefix="/campaign", tags=["campaign"])

WALLET_REQUIRED = "캠페인을 생성하려면 지갑을 먼저 연결해야 합니다."
DEADLINE_PASSED = "마감일은 현재 시각보다 이후여야 합니다."
CAMPAIGN_NOT_FOUND = "존재하지 않는 캠페인입니다."
NOT_OWNER = "해당 캠페인의 총대만 마감할 수 있습니다."
ALREADY_CLOSED = "이미 마감된 캠페인입니다."


@router.post("", status_code=201)
async def create_campaign(
    body: CreateCampaignRequest, user: CurrentUser, session: SessionDep
) -> dict:
    if not user.wallet_address:
        raise HTTPException(status_code=400, detail=WALLET_REQUIRED)

    deadline = body.deadline
    deadline = (
        deadline.replace(tzinfo=timezone.utc)
        if deadline.tzinfo is None
        else deadline.astimezone(timezone.utc)
    )
    if deadline <= utcnow():
        raise HTTPException(status_code=400, detail=DEADLINE_PASSED)

    campaign_uuid = str(uuid4())
    onchain = await chain.post(
        "/tx/campaign",
        {
            "idemKey": campaign_uuid,
            "authority": user.wallet_address,
            "goalAmount": str(body.goal_amount),
            "deadline": int(deadline.timestamp()),
        },
    )

    campaign = Campaign(
        uuid=campaign_uuid,
        title=body.title,
        category=body.category,
        policy=body.policy,
        goal_amount=body.goal_amount,
        deadline=deadline,
        owner_id=user.id,
        authority_wallet=user.wallet_address,
        campaign_pda=onchain["campaignPda"],
        escrow_pda=onchain["escrowPda"],
    )
    session.add(campaign)
    await session.commit()
    await session.refresh(campaign)

    return {"id": campaign.id, "escrowPda": campaign.escrow_pda, "status": campaign.status}


@router.post("/{campaign_id}/close")
async def close_campaign(campaign_id: int, user: CurrentUser, session: SessionDep) -> dict:
    campaign = await session.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail=CAMPAIGN_NOT_FOUND)
    if campaign.owner_id != user.id:
        raise HTTPException(status_code=403, detail=NOT_OWNER)
    if campaign.status != CampaignStatus.FUNDING:
        raise HTTPException(status_code=409, detail=ALREADY_CLOSED)

    result = await chain.post("/tx/close", {"campaignUuid": campaign.uuid})

    campaign.status = settlement.ONCHAIN_STATUS.get(result["status"], campaign.status)
    session.add(campaign)
    await session.commit()

    return {"status": campaign.status, "txSignature": result["signature"]}
