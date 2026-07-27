from pydantic import Field

from app.schemas.base import CamelModel
from app.schemas.vendor import QuoteItem


class SubmitReceiptRequest(CamelModel):
    campaign_id: int
    items: list[QuoteItem] = Field(min_length=1)
    total_amount: int = Field(gt=0)
    file_url: str = Field(min_length=1, max_length=500)
