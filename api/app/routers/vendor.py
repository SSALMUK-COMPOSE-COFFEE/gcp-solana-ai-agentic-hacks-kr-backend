from fastapi import APIRouter, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.core import policy, security, settlement, storage
from app.core.deps import CurrentVendor, ServiceToken, SessionDep
from app.models import Campaign, CampaignStatus, Proof, ProofStatus, ProofType, Vendor
from app.schemas.vendor import RegisterVendorRequest, SubmitQuoteRequest

router = APIRouter(prefix="/vendor", tags=["vendor"])

VENDOR_EXISTS = "이미 등록된 벤더입니다."
VENDOR_NOT_FOUND = "존재하지 않는 벤더입니다."
NOT_ALLOWLISTED = "allowlist에 등재되지 않은 벤더입니다."
CAMPAIGN_NOT_FOUND = "존재하지 않는 캠페인입니다."
CAMPAIGN_CLOSED = "이미 마감된 캠페인입니다."


def _vendor_body(vendor: Vendor) -> dict:
    return {
        "id": vendor.id,
        "name": vendor.name,
        "category": vendor.category,
        "walletAddress": vendor.wallet_address,
        "contact": vendor.contact,
        "allowlisted": vendor.allowlisted,
    }


async def _get_vendor(session: SessionDep, vendor_id: int) -> Vendor:
    vendor = await session.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail=VENDOR_NOT_FOUND)
    return vendor


@router.post("", status_code=201)
async def register_vendor(body: RegisterVendorRequest, session: SessionDep) -> dict:
    api_key = security.create_api_key()
    vendor = Vendor(
        name=body.name,
        wallet_address=body.wallet_address,
        category=body.category,
        contact=body.contact,
        api_key_hash=security.hash_api_key(api_key),
    )

    session.add(vendor)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail=VENDOR_EXISTS) from None

    await session.refresh(vendor)
    return {"id": vendor.id, "allowlisted": vendor.allowlisted, "apiKey": api_key}


@router.get("")
async def list_vendors(session: SessionDep, allowlisted: bool | None = None) -> dict:
    statement = select(Vendor)
    if allowlisted is not None:
        statement = statement.where(Vendor.allowlisted == allowlisted)

    result = await session.exec(statement.order_by(Vendor.id))
    return {"vendors": [_vendor_body(vendor) for vendor in result.all()]}


@router.get("/{vendor_id}")
async def read_vendor(vendor_id: int, session: SessionDep) -> dict:
    return _vendor_body(await _get_vendor(session, vendor_id))


@router.post("/{vendor_id}/allowlist")
async def add_to_allowlist(vendor_id: int, _: ServiceToken, session: SessionDep) -> dict:
    vendor = await _get_vendor(session, vendor_id)
    vendor.allowlisted = True
    session.add(vendor)
    await session.commit()
    return {"message": "allowlist에 등재되었습니다."}


@router.delete("/{vendor_id}/allowlist")
async def remove_from_allowlist(vendor_id: int, _: ServiceToken, session: SessionDep) -> dict:
    vendor = await _get_vendor(session, vendor_id)
    vendor.allowlisted = False
    session.add(vendor)
    await session.commit()
    return {"message": "allowlist에서 해제되었습니다."}


@router.post("/{vendor_id}/quote", status_code=201)
async def submit_quote(
    vendor_id: int, body: SubmitQuoteRequest, vendor: CurrentVendor, session: SessionDep
) -> dict:
    if vendor.id != vendor_id:
        raise HTTPException(status_code=401, detail="벤더 인증이 필요합니다.")
    if not vendor.allowlisted:
        raise HTTPException(status_code=403, detail=NOT_ALLOWLISTED)
    storage.validate_file_url(body.file_url)

    items = [item.model_dump() for item in body.items]
    policy.check_declared_total(items, body.total_amount)

    campaign = await session.get(Campaign, body.campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail=CAMPAIGN_NOT_FOUND)
    if campaign.status == CampaignStatus.CLOSED:
        raise HTTPException(status_code=409, detail=CAMPAIGN_CLOSED)
    if settlement.is_self_dealing(campaign, vendor):
        raise HTTPException(status_code=403, detail=settlement.SELF_DEALING)

    proof = Proof(
        campaign_id=campaign.id,
        vendor_id=vendor.id,
        type=ProofType.QUOTE,
        amount=body.total_amount,
        items=items,
        file_url=body.file_url,
    )
    session.add(proof)
    await session.commit()
    await session.refresh(proof)

    return {"proofId": proof.id, "status": ProofStatus.PENDING}
