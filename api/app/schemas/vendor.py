from pydantic import Field

from app.schemas.base import CamelModel


class RegisterVendorRequest(CamelModel):
    name: str = Field(min_length=1, max_length=100)
    wallet_address: str = Field(min_length=32, max_length=64)
    category: str = Field(min_length=1, max_length=50)
    contact: str | None = Field(default=None, max_length=200)


class QuoteItem(CamelModel):
    name: str = Field(min_length=1, max_length=200)
    unit_price: int = Field(gt=0)
    quantity: int = Field(gt=0)


class SubmitQuoteRequest(CamelModel):
    campaign_id: int
    items: list[QuoteItem] = Field(min_length=1)
    total_amount: int = Field(gt=0)
    file_url: str = Field(min_length=1, max_length=500)
