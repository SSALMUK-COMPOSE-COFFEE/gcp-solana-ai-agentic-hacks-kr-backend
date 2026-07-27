from datetime import timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from app.core import chain
from app.core.deps import CurrentUser, SessionDep
from app.models import Campaign, utcnow
from app.schemas.campaign import CreateCampaignRequest

router = APIRouter(prefix="/campaign", tags=["campaign"])

WALLET_REQUIRED = "캠페인을 생성하려면 지갑을 먼저 연결해야 합니다."
DEADLINE_PASSED = "마감일은 현재 시각보다 이후여야 합니다."


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
