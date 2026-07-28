from fastapi import APIRouter, File, HTTPException, UploadFile

from app.core import storage
from app.core.deps import CurrentVendor, SessionDep
from app.models import Campaign, Proof, ProofType, Vendor
from app.schemas.proof import SubmitReceiptRequest

router = APIRouter(prefix="/proof", tags=["proof"])

CAMPAIGN_NOT_FOUND = "존재하지 않는 캠페인입니다."
PROOF_NOT_FOUND = "존재하지 않는 증빙입니다."
NOT_ALLOWLISTED = "allowlist에 등재되지 않은 벤더입니다."


@router.post("/upload", status_code=201)
async def upload_document(vendor: CurrentVendor, file: UploadFile = File(...)) -> dict:
    if not vendor.allowlisted:
        raise HTTPException(status_code=403, detail=NOT_ALLOWLISTED)

    content = await file.read()
    return {"fileUrl": storage.save(content, file.content_type or "")}


@router.post("/receipt", status_code=201)
async def submit_receipt(
    body: SubmitReceiptRequest, vendor: CurrentVendor, session: SessionDep
) -> dict:
    if not vendor.allowlisted:
        raise HTTPException(status_code=403, detail=NOT_ALLOWLISTED)

    campaign = await session.get(Campaign, body.campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail=CAMPAIGN_NOT_FOUND)

    proof = Proof(
        campaign_id=campaign.id,
        vendor_id=vendor.id,
        type=ProofType.RECEIPT,
        amount=body.total_amount,
        items=[item.model_dump() for item in body.items],
        file_url=body.file_url,
    )
    session.add(proof)
    await session.commit()
    await session.refresh(proof)

    return {"proofId": proof.id, "status": proof.status}


@router.get("/{proof_id}")
async def read_proof(proof_id: int, session: SessionDep) -> dict:
    proof = await session.get(Proof, proof_id)
    if proof is None:
        raise HTTPException(status_code=404, detail=PROOF_NOT_FOUND)

    vendor = await session.get(Vendor, proof.vendor_id) if proof.vendor_id else None

    return {
        "proofId": proof.id,
        "campaignId": proof.campaign_id,
        "type": proof.type,
        "vendorId": proof.vendor_id,
        "vendorName": vendor.name if vendor else None,
        "amount": proof.amount,
        "items": proof.items,
        "status": proof.status,
        "fileUrl": proof.file_url,
        "releaseTx": proof.release_tx,
        "createdAt": proof.created_at,
    }
