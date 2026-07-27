from pydantic import Field

from app.schemas.base import CamelModel


class PaymentQrRequest(CamelModel):
    campaign_id: int
    amount: int = Field(gt=0)


class SolanaPayTxRequest(CamelModel):
    account: str
