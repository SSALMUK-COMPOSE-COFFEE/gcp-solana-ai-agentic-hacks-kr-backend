from fastapi import HTTPException
from sqlalchemy import func
from sqlmodel import select

from app.models import Campaign, Micropay, Proof, ProofType, Vendor

RULE_MODEL = "rule-based"
BUDGET_EXHAUSTED = "이 캠페인의 AI 심사 예산이 소진되었습니다."


async def ai_review_spent(session, campaign_id: int) -> int:
    result = await session.exec(
        select(func.coalesce(func.sum(Micropay.amount), 0)).where(
            Micropay.campaign_id == campaign_id,
            Micropay.paid == True,  # noqa: E712
        )
    )
    return int(result.one())


async def check_ai_review_budget(session, campaign: Campaign, cost: int) -> dict:
    budget = (campaign.policy or {}).get("aiReviewBudget")
    spent = await ai_review_spent(session, campaign.id)
    if isinstance(budget, int) and spent + cost > budget:
        raise HTTPException(
            status_code=402,
            detail=f"{BUDGET_EXHAUSTED} (한도 {budget} / 사용 {spent} / 이번 심사 {cost} raw units)",
        )
    return {"budget": budget, "spent": spent}


def items_total(items: list[dict]) -> int:
    return sum(item.get("unit_price", 0) * item.get("quantity", 0) for item in items)


def check_declared_total(items: list[dict], total_amount: int) -> None:
    expected = items_total(items)
    if total_amount != expected:
        raise HTTPException(
            status_code=400,
            detail=f"신고 총액 {total_amount}가 항목 합계 {expected}와 다릅니다.",
        )


def _scaled(limit: int, campaign: Campaign) -> int:
    if not campaign.policy.get("allowSurplusScaling"):
        return limit
    if campaign.goal_amount <= 0 or campaign.raised_amount <= campaign.goal_amount:
        return limit
    return limit * campaign.raised_amount // campaign.goal_amount


async def _released_in_category(session, campaign: Campaign, category: str) -> int:
    result = await session.exec(
        select(func.coalesce(func.sum(Proof.amount), 0))
        .join(Vendor, Vendor.id == Proof.vendor_id)
        .where(
            Proof.campaign_id == campaign.id,
            Proof.type == ProofType.QUOTE,
            Proof.release_tx.is_not(None),
            Vendor.category == category,
        )
    )
    return int(result.one())


async def violations(
    session, campaign: Campaign, vendor: Vendor, proof: Proof, amount: int
) -> list[str]:
    policy = campaign.policy or {}
    categories = policy.get("categories") or {}
    found: list[str] = []

    declared = items_total(proof.items)
    if declared != proof.amount:
        found.append(f"신고 총액 {proof.amount}가 항목 합계 {declared}와 다릅니다.")

    if (
        categories
        and vendor.category != campaign.category
        and vendor.category not in categories
    ):
        found.append(f"벤더 카테고리 '{vendor.category}'는 캠페인 정책에 없는 카테고리입니다.")
        return found

    limits = categories.get(vendor.category) or {}

    max_unit_price = limits.get("maxUnitPrice")
    if isinstance(max_unit_price, int):
        cap = _scaled(max_unit_price, campaign)
        for item in proof.items:
            unit_price = item.get("unit_price", 0)
            if unit_price > cap:
                found.append(
                    f"'{item.get('name')}' 단가 {unit_price}가 상한 {cap}를 초과합니다."
                )

    max_total = limits.get("maxTotal")
    if not isinstance(max_total, int):
        max_total = policy.get("maxPerCategory")
    if isinstance(max_total, int):
        cap = _scaled(max_total, campaign)
        cumulative = await _released_in_category(session, campaign, vendor.category)
        if cumulative + amount > cap:
            found.append(
                f"카테고리 '{vendor.category}' 누적 집행 {cumulative + amount}가 "
                f"총액 상한 {cap}를 초과합니다."
            )

    return found
