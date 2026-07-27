from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from sqlmodel import select

from app.core import chain, settlement
from app.core.deps import CurrentUser, SessionDep
from app.models import (
    Campaign,
    CampaignStatus,
    Contribution,
    Proof,
    RewardTier,
    User,
    Vendor,
    utcnow,
)
from app.schemas.campaign import (
    CreateCampaignRequest,
    CreateTierRequest,
    UpdateCampaignRequest,
)

router = APIRouter(prefix="/campaign", tags=["campaign"])

WALLET_REQUIRED = "캠페인을 생성하려면 지갑을 먼저 연결해야 합니다."
DEADLINE_PASSED = "마감일은 현재 시각보다 이후여야 합니다."
CAMPAIGN_NOT_FOUND = "존재하지 않는 캠페인입니다."
NOT_OWNER = "해당 캠페인의 총대만 마감할 수 있습니다."
ALREADY_CLOSED = "이미 마감된 캠페인입니다."
BAD_QUERY = "잘못된 요청입니다."
NOT_EDITABLE = "수정 권한이 없습니다."
ALREADY_FUNDED = "이미 모금이 시작된 캠페인입니다."
DEADLINE_EXTEND = "마감일은 앞당기는 것만 가능합니다."


def _to_utc(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def _mask_wallet(address: str) -> str:
    return f"{address[:4]}…{address[-4:]}"


async def _load_campaign(session, campaign_id: int) -> Campaign:
    campaign = await session.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail=CAMPAIGN_NOT_FOUND)
    return campaign


@router.post("", status_code=201)
async def create_campaign(
    body: CreateCampaignRequest, user: CurrentUser, session: SessionDep
) -> dict:
    if not user.wallet_address:
        raise HTTPException(status_code=400, detail=WALLET_REQUIRED)

    deadline = _to_utc(body.deadline)
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
        policy=body.policy.to_stored(),
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


@router.get("")
async def list_campaigns(
    session: SessionDep, status: str | None = None, category: str | None = None
) -> dict:
    if status is not None and status not in CampaignStatus.ALL:
        raise HTTPException(status_code=400, detail=BAD_QUERY)

    stmt = select(Campaign).order_by(Campaign.created_at.desc())
    if category is not None:
        stmt = stmt.where(Campaign.category == category)
    result = await session.exec(stmt)

    campaigns = []
    for campaign in result.all():
        effective = settlement.overdue_status(campaign)
        if status is not None and effective != status:
            continue
        campaigns.append(
            {
                "id": campaign.id,
                "title": campaign.title,
                "category": campaign.category,
                "goalAmount": campaign.goal_amount,
                "raisedAmount": campaign.raised_amount,
                "deadline": campaign.deadline,
                "status": effective,
            }
        )

    return {"campaigns": campaigns}


@router.get("/{campaign_id}")
async def read_campaign(campaign_id: int, session: SessionDep) -> dict:
    campaign = await _load_campaign(session, campaign_id)
    await settlement.lazy_close(session, campaign)

    return {
        "id": campaign.id,
        "title": campaign.title,
        "category": campaign.category,
        "goalAmount": campaign.goal_amount,
        "raisedAmount": campaign.raised_amount,
        "deadline": campaign.deadline,
        "escrowPda": campaign.escrow_pda,
        "status": settlement.overdue_status(campaign),
        "policy": campaign.policy,
    }


@router.post("/{campaign_id}")
async def update_campaign(
    campaign_id: int, body: UpdateCampaignRequest, user: CurrentUser, session: SessionDep
) -> dict:
    campaign = await _load_campaign(session, campaign_id)
    if campaign.owner_id != user.id:
        raise HTTPException(status_code=403, detail=NOT_EDITABLE)
    if campaign.status != CampaignStatus.FUNDING or campaign.raised_amount > 0:
        raise HTTPException(status_code=409, detail=ALREADY_FUNDED)

    if body.title is not None:
        campaign.title = body.title
    if body.policy is not None:
        campaign.policy = body.policy.to_stored()
    if body.deadline is not None:
        deadline = _to_utc(body.deadline)
        if deadline <= utcnow():
            raise HTTPException(status_code=400, detail=DEADLINE_PASSED)
        if deadline > campaign.deadline:
            raise HTTPException(status_code=400, detail=DEADLINE_EXTEND)
        campaign.deadline = deadline

    session.add(campaign)
    await session.commit()

    return {"message": "캠페인이 수정되었습니다."}


@router.get("/{campaign_id}/status")
async def read_campaign_status(campaign_id: int, session: SessionDep) -> dict:
    campaign = await _load_campaign(session, campaign_id)
    await settlement.lazy_close(session, campaign)

    remaining = int((campaign.deadline - utcnow()).total_seconds())

    return {
        "goalAmount": campaign.goal_amount,
        "raisedAmount": campaign.raised_amount,
        "progressRate": round(campaign.raised_amount / campaign.goal_amount, 4),
        "contributorCount": campaign.contributor_count,
        "remainingSeconds": max(remaining, 0),
        "status": settlement.overdue_status(campaign),
    }


@router.get("/{campaign_id}/contributions")
async def read_campaign_contributions(campaign_id: int, session: SessionDep) -> dict:
    await _load_campaign(session, campaign_id)

    result = await session.exec(
        select(Contribution, User)
        .join(User, User.id == Contribution.user_id, isouter=True)
        .where(Contribution.campaign_id == campaign_id)
        .order_by(Contribution.created_at.desc())
    )
    rows = result.all()

    return {
        "contributions": [
            {
                "userId": contribution.user_id,
                "name": user.name if user else _mask_wallet(contribution.wallet_address),
                "amount": contribution.amount,
                "txSignature": contribution.tx_signature,
                "createdAt": contribution.created_at,
            }
            for contribution, user in rows
        ],
        "totalCount": len(rows),
    }


@router.get("/{campaign_id}/quotes")
async def read_campaign_quotes(campaign_id: int, session: SessionDep) -> dict:
    await _load_campaign(session, campaign_id)

    result = await session.exec(
        select(Proof, Vendor)
        .join(Vendor, Vendor.id == Proof.vendor_id, isouter=True)
        .where(Proof.campaign_id == campaign_id)
        .order_by(Proof.created_at.desc())
    )

    return {
        "quotes": [
            {
                "proofId": proof.id,
                "type": proof.type,
                "vendorId": proof.vendor_id,
                "vendorName": vendor.name if vendor else None,
                "amount": proof.amount,
                "status": proof.status,
                "fileUrl": proof.file_url,
            }
            for proof, vendor in result.all()
        ]
    }


@router.post("/{campaign_id}/tiers", status_code=201)
async def create_tier(
    campaign_id: int, body: CreateTierRequest, user: CurrentUser, session: SessionDep
) -> dict:
    campaign = await _load_campaign(session, campaign_id)
    if campaign.owner_id != user.id:
        raise HTTPException(status_code=403, detail=NOT_EDITABLE)
    if campaign.status != CampaignStatus.FUNDING:
        raise HTTPException(status_code=409, detail=ALREADY_CLOSED)

    tier = RewardTier(
        campaign_id=campaign_id,
        title=body.title,
        price=body.price,
        items=body.items,
        limit=body.limit,
    )
    session.add(tier)
    await session.commit()
    await session.refresh(tier)

    return {"tierId": tier.id}


@router.get("/{campaign_id}/tiers")
async def read_tiers(campaign_id: int, session: SessionDep) -> dict:
    await _load_campaign(session, campaign_id)

    result = await session.exec(
        select(RewardTier)
        .where(RewardTier.campaign_id == campaign_id)
        .order_by(RewardTier.price.asc())
    )

    return {
        "tiers": [
            {
                "tierId": tier.id,
                "title": tier.title,
                "price": tier.price,
                "items": tier.items,
                "limit": tier.limit,
                "soldCount": tier.sold_count,
                "remaining": tier.limit - tier.sold_count if tier.limit is not None else None,
            }
            for tier in result.all()
        ]
    }


@router.post("/{campaign_id}/close")
async def close_campaign(campaign_id: int, user: CurrentUser, session: SessionDep) -> dict:
    campaign = await _load_campaign(session, campaign_id)
    if campaign.owner_id != user.id:
        raise HTTPException(status_code=403, detail=NOT_OWNER)
    if campaign.status != CampaignStatus.FUNDING:
        raise HTTPException(status_code=409, detail=ALREADY_CLOSED)

    result = await chain.post("/tx/close", {"campaignUuid": campaign.uuid})

    campaign.status = settlement.ONCHAIN_STATUS.get(result["status"], campaign.status)
    session.add(campaign)
    await session.commit()

    return {"status": campaign.status, "txSignature": result["signature"]}
