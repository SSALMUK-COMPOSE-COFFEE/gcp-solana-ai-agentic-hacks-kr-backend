from app.schemas.base import CamelModel


class EvaluatePolicyRequest(CamelModel):
    campaign_id: int
    proof_id: int
