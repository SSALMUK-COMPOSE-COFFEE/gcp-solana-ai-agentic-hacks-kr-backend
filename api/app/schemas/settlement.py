from pydantic import Field

from app.schemas.base import CamelModel


class ReleaseRequest(CamelModel):
    vendor_id: int
    proof_id: int
    amount: int = Field(gt=0)
