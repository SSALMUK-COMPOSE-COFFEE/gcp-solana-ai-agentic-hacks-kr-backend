from fastapi import APIRouter, HTTPException
from sqlmodel import select

from app.core.deps import CurrentUser, SessionDep
from app.models import (
    Campaign,
    CampaignStatus,
    Certificate,
    Contribution,
    PaymentRequest,
    User,
)
from app.schemas.user import UpdateProfileRequest

router = APIRouter(prefix="/users", tags=["users"])

USER_NOT_FOUND = "존재하지 않는 유저입니다."
CAMPAIGN_IN_PROGRESS = "진행 중인 캠페인이 있어 탈퇴할 수 없습니다."


@router.get("/me")
async def read_me(user: CurrentUser) -> dict:
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "walletAddress": user.wallet_address,
        "bio": user.bio,
        "avatarUrl": user.avatar_url,
    }


@router.post("/me")
async def update_me(body: UpdateProfileRequest, user: CurrentUser, session: SessionDep) -> dict:
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(user, field, value)

    session.add(user)
    await session.commit()

    return {"message": "프로필이 수정되었습니다."}


@router.get("/me/tiny")
async def read_me_tiny(user: CurrentUser) -> dict:
    return {"id": user.id, "name": user.name}


@router.get("/me/contributions")
async def read_my_contributions(user: CurrentUser, session: SessionDep) -> dict:
    result = await session.exec(
        select(Contribution, Campaign)
        .join(Campaign, Campaign.id == Contribution.campaign_id)
        .where(Contribution.user_id == user.id)
        .order_by(Contribution.created_at.desc())
    )

    return {
        "contributions": [
            {
                "campaignId": campaign.id,
                "title": campaign.title,
                "amount": contribution.amount,
                "currency": "USDC",
                "status": campaign.status,
                "createdAt": contribution.created_at,
            }
            for contribution, campaign in result.all()
        ]
    }


@router.get("/me/certificates")
async def read_my_certificates(user: CurrentUser, session: SessionDep) -> dict:
    result = await session.exec(
        select(Certificate, Campaign)
        .join(Campaign, Campaign.id == Certificate.campaign_id)
        .where(Certificate.user_id == user.id)
        .order_by(Certificate.issued_at.desc())
    )

    return {
        "certificates": [
            {
                "mintAddress": certificate.mint_address,
                "campaignId": campaign.id,
                "campaignTitle": campaign.title,
                "imageUrl": certificate.image_url,
                "issuedAt": certificate.issued_at,
            }
            for certificate, campaign in result.all()
        ]
    }


@router.delete("/me/withdraw")
async def withdraw(user: CurrentUser, session: SessionDep) -> dict:
    owned = await session.exec(
        select(Campaign).where(
            Campaign.owner_id == user.id,
            Campaign.status != CampaignStatus.CLOSED,
        )
    )
    if owned.first() is not None:
        raise HTTPException(status_code=409, detail=CAMPAIGN_IN_PROGRESS)

    contributions = await session.exec(
        select(Contribution).where(Contribution.user_id == user.id)
    )
    payments = await session.exec(
        select(PaymentRequest).where(PaymentRequest.user_id == user.id)
    )
    for record in [*contributions.all(), *payments.all()]:
        record.user_id = None
        session.add(record)

    certificates = await session.exec(
        select(Certificate).where(Certificate.user_id == user.id)
    )
    for certificate in certificates.all():
        await session.delete(certificate)

    await session.delete(user)
    await session.commit()

    return {"message": "탈퇴가 완료되었습니다."}


@router.get("/{user_id}")
async def read_user(user_id: int, session: SessionDep) -> dict:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=USER_NOT_FOUND)

    return {
        "id": user.id,
        "name": user.name,
        "bio": user.bio,
        "walletAddress": user.wallet_address,
        "avatarUrl": user.avatar_url,
    }
