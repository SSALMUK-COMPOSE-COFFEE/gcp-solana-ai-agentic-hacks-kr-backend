from uuid import uuid4

from fastapi import HTTPException

from app.core import chain
from app.models import (
    AgentDecision,
    AgentDecisionType,
    AgentRole,
    Campaign,
    CampaignStatus,
    Proof,
    ProofStatus,
    ProofType,
    Vendor,
    utcnow,
)

NOT_ALLOWLISTED = "검증되지 않은 지출이거나 allowlist 벤더가 아닙니다."
NOT_QUOTE = "견적 증빙만 집행할 수 있습니다."
ALREADY_RELEASED = "이미 지급된 증빙입니다."
NOT_EXECUTING = "집행 가능한 상태의 캠페인이 아닙니다."
INSUFFICIENT = "에스크로 잔액이 부족합니다."
SELF_DEALING = "총대 지갑과 동일한 벤더에게는 집행할 수 없습니다."

ONCHAIN_STATUS = {
    "Funding": CampaignStatus.FUNDING,
    "Executing": CampaignStatus.EXECUTING,
    "Refunding": CampaignStatus.REFUNDING,
    "Closed": CampaignStatus.CLOSED,
}


def overdue_status(campaign: Campaign) -> str:
    if campaign.status != CampaignStatus.FUNDING or campaign.deadline > utcnow():
        return campaign.status
    if campaign.raised_amount >= campaign.goal_amount:
        return CampaignStatus.EXECUTING
    if campaign.contributor_count > 0:
        return CampaignStatus.REFUNDING
    return CampaignStatus.CLOSED


async def lazy_close(session, campaign: Campaign) -> None:
    if campaign.status != CampaignStatus.FUNDING or campaign.deadline > utcnow():
        return

    try:
        result = await chain.post("/tx/close", {"campaignUuid": campaign.uuid})
    except HTTPException:
        return

    campaign.status = ONCHAIN_STATUS.get(result["status"], campaign.status)
    session.add(campaign)
    await session.commit()


def available_balance(campaign: Campaign) -> int:
    return campaign.raised_amount - campaign.released_amount - campaign.refunded_amount


def is_self_dealing(campaign: Campaign, vendor: Vendor) -> bool:
    return vendor.wallet_address == campaign.authority_wallet


def check_releasable(campaign: Campaign, vendor: Vendor | None, proof: Proof, amount: int) -> None:
    if proof.type != ProofType.QUOTE:
        raise HTTPException(status_code=409, detail=NOT_QUOTE)
    if vendor is None or not vendor.allowlisted or proof.status != ProofStatus.APPROVED:
        raise HTTPException(status_code=403, detail=NOT_ALLOWLISTED)
    if is_self_dealing(campaign, vendor):
        raise HTTPException(status_code=403, detail=SELF_DEALING)
    if proof.release_tx is not None:
        raise HTTPException(status_code=409, detail=ALREADY_RELEASED)
    if campaign.status != CampaignStatus.EXECUTING:
        raise HTTPException(status_code=409, detail=NOT_EXECUTING)
    if amount > available_balance(campaign):
        raise HTTPException(status_code=409, detail=INSUFFICIENT)


async def release(
    session, campaign: Campaign, vendor: Vendor, proof: Proof, amount: int
) -> dict:
    check_releasable(campaign, vendor, proof, amount)

    result = await chain.post(
        "/tx/release",
        {
            "idemKey": str(uuid4()),
            "campaignUuid": campaign.uuid,
            "vendorWallet": vendor.wallet_address,
            "amount": str(amount),
        },
    )

    proof.release_tx = result["signature"]
    campaign.released_amount += amount
    if result.get("status") in ONCHAIN_STATUS:
        campaign.status = ONCHAIN_STATUS[result["status"]]

    session.add_all(
        [
            campaign,
            proof,
            AgentDecision(
                campaign_id=campaign.id,
                proof_id=proof.id,
                role=AgentRole.SETTLEMENT_REFUND,
                decision=AgentDecisionType.APPROVE,
                required_amount=0,
                reasons=[
                    f"승인된 증빙 {proof.id}에 대해 벤더 {vendor.name}에게 {amount} raw units 집행",
                    f"트랜잭션 {result['signature']}",
                ],
                model="onchain",
            ),
        ]
    )
    await session.commit()

    return {"txSignature": result["signature"], "releasedAmount": amount}
