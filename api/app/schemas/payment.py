from pydantic import Field

from app.schemas.base import CamelModel


class PaymentQrRequest(CamelModel):
    campaign_id: int
    amount: int | None = Field(default=None, gt=0)
    tier_id: int | None = None


class SolanaPayTxRequest(CamelModel):
    account: str


class MicropayRequest(CamelModel):
    resource: str = Field(min_length=1, max_length=100)
    amount: int = Field(gt=0)


class PayshWebhookPayload(CamelModel):
    resource: str
    paid: bool
    tx_signature: str
