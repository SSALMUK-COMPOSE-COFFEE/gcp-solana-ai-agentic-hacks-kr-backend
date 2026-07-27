from fastapi import APIRouter, HTTPException
from sqlmodel import select

from app.core import gemini
from app.core.config import settings
from app.core.deps import AgentCaller, SessionDep
from app.models import (
    AgentDecision,
    AgentDecisionType,
    AgentRole,
    Campaign,
    Proof,
    ProofStatus,
    Vendor,
)
from app.schemas.agent import EvaluatePolicyRequest

router = APIRouter(prefix="/agent", tags=["agent"])

CAMPAIGN_NOT_FOUND = "존재하지 않는 캠페인입니다."
PROOF_NOT_FOUND = "존재하지 않는 증빙입니다."
NOT_OWNER = "해당 캠페인의 총대만 요청할 수 있습니다."


@router.post("/policy/evaluate")
async def evaluate_policy(
    body: EvaluatePolicyRequest, caller: AgentCaller, session: SessionDep
) -> dict:
    campaign = await session.get(Campaign, body.campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail=CAMPAIGN_NOT_FOUND)
    if caller is not None and campaign.owner_id != caller.id:
        raise HTTPException(status_code=403, detail=NOT_OWNER)

    proof = await session.get(Proof, body.proof_id)
    if proof is None or proof.campaign_id != campaign.id:
        raise HTTPException(status_code=404, detail=PROOF_NOT_FOUND)

    vendor = await session.get(Vendor, proof.vendor_id) if proof.vendor_id else None

    prompt = gemini.build_prompt(
        campaign={
            "제목": campaign.title,
            "카테고리": campaign.category,
            "목표금액": gemini.amount(campaign.goal_amount),
            "모금액": gemini.amount(campaign.raised_amount),
            "집행액": gemini.amount(campaign.released_amount),
            "마감": campaign.deadline.isoformat(),
            "상태": campaign.status,
            "정책": campaign.policy,
        },
        vendor={
            "이름": vendor.name if vendor else None,
            "카테고리": vendor.category if vendor else None,
            "지갑": vendor.wallet_address if vendor else None,
            "allowlist_등재": vendor.allowlisted if vendor else False,
        },
        proof={
            "종류": proof.type,
            "신고_총액": gemini.amount(proof.amount),
            "항목": [
                {
                    "이름": item.get("name"),
                    "단가": gemini.amount(item.get("unit_price", 0)),
                    "수량": item.get("quantity"),
                }
                for item in proof.items
            ],
            "첨부파일": bool(proof.file_url),
        },
        escrow_balance=campaign.raised_amount - campaign.released_amount,
    )

    document = await gemini.fetch_document(proof.file_url)
    decision = await gemini.evaluate_policy(prompt, document)
    approved = decision.decision == AgentDecisionType.APPROVE

    proof.status = ProofStatus.APPROVED if approved else ProofStatus.REJECTED
    record = AgentDecision(
        campaign_id=campaign.id,
        proof_id=proof.id,
        role=AgentRole.ORCHESTRATOR,
        decision=decision.decision,
        required_amount=decision.required_amount,
        reasons=decision.reasons,
        model=settings.gemini_model,
        read_file=document is not None,
    )

    session.add_all([proof, record])
    await session.commit()

    return {
        "decision": decision.decision,
        "requiredAmount": decision.required_amount,
        "reasons": decision.reasons,
        "readFile": document is not None,
        "model": settings.gemini_model,
    }


@router.get("/{campaign_id}/decisions")
async def read_decisions(campaign_id: int, session: SessionDep) -> dict:
    campaign = await session.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail=CAMPAIGN_NOT_FOUND)

    result = await session.exec(
        select(AgentDecision)
        .where(AgentDecision.campaign_id == campaign_id)
        .order_by(AgentDecision.created_at.desc())
    )

    return {
        "decisions": [
            {
                "id": decision.id,
                "proofId": decision.proof_id,
                "role": decision.role,
                "decision": decision.decision,
                "requiredAmount": decision.required_amount,
                "reasons": decision.reasons,
                "model": decision.model,
                "readFile": decision.read_file,
                "createdAt": decision.created_at,
            }
            for decision in result.all()
        ]
    }
