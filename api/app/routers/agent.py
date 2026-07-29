from fastapi import APIRouter, HTTPException
from sqlmodel import select

from app.core import gemini, paysh, policy, settlement
from app.core.config import settings
from app.core.deps import AgentCaller, CurrentUser, SessionDep
from app.models import (
    AgentDecision,
    AgentDecisionType,
    AgentRole,
    Campaign,
    CampaignStatus,
    Proof,
    ProofStatus,
    RewardTier,
    Vendor,
)
from app.models.proof import ProofType
from app.schemas.agent import AuditRequest, EvaluatePolicyRequest

router = APIRouter(prefix="/agent", tags=["agent"])

CAMPAIGN_NOT_FOUND = "존재하지 않는 캠페인입니다."
PROOF_NOT_FOUND = "존재하지 않는 증빙입니다."
NOT_OWNER = "해당 캠페인의 총대만 요청할 수 있습니다."
NOT_QUOTE = "영수증 증빙은 정책 심사 대상이 아닙니다. 사후 감사(/agent/audit)로 검증됩니다."
ALREADY_RELEASED = "이미 집행된 증빙은 다시 심사할 수 없습니다."


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
    if proof.type != ProofType.QUOTE:
        raise HTTPException(status_code=409, detail=NOT_QUOTE)
    if proof.release_tx is not None:
        raise HTTPException(status_code=409, detail=ALREADY_RELEASED)

    vendor = await session.get(Vendor, proof.vendor_id) if proof.vendor_id else None

    if vendor is not None:
        found = await policy.violations(session, campaign, vendor, proof, proof.amount)
        if found:
            proof.status = ProofStatus.REJECTED
            session.add_all(
                [
                    proof,
                    AgentDecision(
                        campaign_id=campaign.id,
                        proof_id=proof.id,
                        role=AgentRole.ORCHESTRATOR,
                        decision=AgentDecisionType.REJECT,
                        required_amount=0,
                        reasons=found,
                        model=policy.RULE_MODEL,
                    ),
                ]
            )
            await session.commit()
            return {
                "decision": AgentDecisionType.REJECT,
                "requiredAmount": 0,
                "reasons": found,
                "readFile": False,
                "model": policy.RULE_MODEL,
                "micropay": {"paid": False, "reason": "정책 위반 룰 거절 — AI 심사 미호출"},
                "execution": None,
            }

    tier_rows = await session.exec(
        select(RewardTier).where(RewardTier.campaign_id == campaign.id)
    )
    tiers = [
        {
            "이름": tier.title,
            "가격": gemini.amount(tier.price),
            "구성품": tier.items,
            "판매수": tier.sold_count,
            "한정수량": tier.limit,
        }
        for tier in tier_rows.all()
    ]

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
            "총대_지갑": campaign.authority_wallet,
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
        escrow_balance=settlement.available_balance(campaign),
        tiers=tiers,
    )

    document = await gemini.fetch_document(proof.file_url)
    decision = await gemini.evaluate_policy(prompt, document)
    approved = decision.decision == AgentDecisionType.APPROVE

    try:
        micropay = await paysh.micropay(
            session, settings.gemini_model, settings.paysh_gemini_cost, campaign.id
        )
        micropay_result = {"paid": True, "txSignature": micropay.tx_signature}
    except HTTPException as failed:
        micropay_result = {"paid": False, "reason": failed.detail}

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
        "micropay": micropay_result,
        "execution": await _execute(session, campaign, vendor, proof) if approved else None,
    }


async def _execute(
    session: SessionDep, campaign: Campaign, vendor: Vendor | None, proof: Proof
) -> dict:
    try:
        result = await settlement.release(session, campaign, vendor, proof, proof.amount)
    except HTTPException as failed:
        return {"executed": False, "reason": failed.detail}

    return {"executed": True, **result}


STATES_BY_STATUS = {
    CampaignStatus.FUNDING: {
        AgentRole.ORCHESTRATOR: "running",
        AgentRole.VENDOR_NEGOTIATION: "running",
        AgentRole.VERIFY_AUDIT: "idle",
        AgentRole.SETTLEMENT_REFUND: "waiting",
    },
    CampaignStatus.EXECUTING: {
        AgentRole.ORCHESTRATOR: "running",
        AgentRole.VENDOR_NEGOTIATION: "idle",
        AgentRole.VERIFY_AUDIT: "running",
        AgentRole.SETTLEMENT_REFUND: "running",
    },
    CampaignStatus.REFUNDING: {
        AgentRole.ORCHESTRATOR: "running",
        AgentRole.VENDOR_NEGOTIATION: "idle",
        AgentRole.VERIFY_AUDIT: "idle",
        AgentRole.SETTLEMENT_REFUND: "running",
    },
    CampaignStatus.CLOSED: {role: "idle" for role in AgentRole.ALL},
}

STATE_RANK = {"idle": 0, "waiting": 1, "running": 2}


@router.get("/status")
async def agent_status(
    user: CurrentUser, session: SessionDep, campaignId: int | None = None
) -> dict:
    if campaignId is not None:
        campaign = await session.get(Campaign, campaignId)
        if campaign is None:
            raise HTTPException(status_code=404, detail=CAMPAIGN_NOT_FOUND)
        states = STATES_BY_STATUS[settlement.overdue_status(campaign)]
        campaign_ids = [campaign.id]
    else:
        result = await session.exec(select(Campaign).where(Campaign.owner_id == user.id))
        campaigns = result.all()
        states = {role: "idle" for role in AgentRole.ALL}
        for campaign in campaigns:
            for role, state in STATES_BY_STATUS[settlement.overdue_status(campaign)].items():
                if STATE_RANK[state] > STATE_RANK[states[role]]:
                    states[role] = state
        campaign_ids = [c.id for c in campaigns]

    last_by_role: dict[str, AgentDecision] = {}
    if campaign_ids:
        result = await session.exec(
            select(AgentDecision)
            .where(AgentDecision.campaign_id.in_(campaign_ids))
            .order_by(AgentDecision.created_at.desc())
            .limit(50)
        )
        for decision in result.all():
            last_by_role.setdefault(decision.role, decision)

    return {
        "agents": [
            {
                "role": role,
                "state": states[role],
                "lastDecision": (
                    {
                        "decision": last_by_role[role].decision,
                        "reason": last_by_role[role].reasons[0] if last_by_role[role].reasons else None,
                        "at": last_by_role[role].created_at,
                    }
                    if role in last_by_role
                    else None
                ),
            }
            for role in AgentRole.ALL
        ]
    }


@router.post("/audit")
async def audit(body: AuditRequest, caller: AgentCaller, session: SessionDep) -> dict:
    campaign = await session.get(Campaign, body.campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail=CAMPAIGN_NOT_FOUND)
    if caller is not None and campaign.owner_id != caller.id:
        raise HTTPException(status_code=403, detail=NOT_OWNER)

    result = await session.exec(select(Proof).where(Proof.campaign_id == campaign.id))
    proofs = result.all()
    released = [p for p in proofs if p.type == ProofType.QUOTE and p.release_tx is not None]
    receipts = [p for p in proofs if p.type == ProofType.RECEIPT]

    flagged = []
    blocked_vendors: set[int] = set()
    for quote in released:
        vendor_receipts = [r for r in receipts if r.vendor_id == quote.vendor_id]
        if not vendor_receipts:
            flagged.append(
                {
                    "proofId": quote.id,
                    "vendorId": quote.vendor_id,
                    "reason": f"집행액 {quote.amount} raw units에 대한 영수증 미제출",
                }
            )
            blocked_vendors.add(quote.vendor_id)
            continue

        matched = next((r for r in vendor_receipts if r.amount == quote.amount), None)
        if matched is None:
            submitted = ", ".join(str(r.amount) for r in vendor_receipts)
            flagged.append(
                {
                    "proofId": quote.id,
                    "vendorId": quote.vendor_id,
                    "reason": f"집행액 {quote.amount} ↔ 영수증 [{submitted}] 금액 불일치",
                }
            )
            blocked_vendors.add(quote.vendor_id)
        elif matched.status == ProofStatus.PENDING:
            matched.status = ProofStatus.APPROVED
            session.add(matched)

    for vendor_id in blocked_vendors:
        vendor = await session.get(Vendor, vendor_id)
        if vendor is not None and vendor.allowlisted:
            vendor.allowlisted = False
            session.add(vendor)

    passed = not flagged
    session.add(
        AgentDecision(
            campaign_id=campaign.id,
            role=AgentRole.VERIFY_AUDIT,
            decision=AgentDecisionType.APPROVE if passed else AgentDecisionType.REJECT,
            reasons=(
                [f"집행 {len(released)}건 전수 감사 — 영수증 대조 이상 없음"]
                if passed
                else [item["reason"] for item in flagged]
                + [f"벤더 {sorted(blocked_vendors)} allowlist 차단"]
            ),
            model="rule-based",
        )
    )
    await session.commit()

    return {"passed": passed, "flagged": flagged, "checkedCount": len(released)}


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
