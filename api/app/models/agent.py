from datetime import datetime

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from app.models.base import amount_zero_column, dt_column, utcnow


class AgentRole:
    ORCHESTRATOR = "orchestrator"
    VENDOR_NEGOTIATION = "vendor-negotiation"
    VERIFY_AUDIT = "verify-audit"
    SETTLEMENT_REFUND = "settlement-refund"

    ALL = (ORCHESTRATOR, VENDOR_NEGOTIATION, VERIFY_AUDIT, SETTLEMENT_REFUND)


class AgentDecisionType:
    APPROVE = "approve"
    REJECT = "reject"

    ALL = (APPROVE, REJECT)


class AgentDecision(SQLModel, table=True):
    __tablename__ = "agent_decisions"

    id: int | None = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="campaigns.id", index=True)
    proof_id: int | None = Field(default=None, foreign_key="proofs.id", index=True)

    role: str = Field(index=True)
    decision: str = Field(index=True)
    required_amount: int = Field(default=0, sa_column=amount_zero_column())
    reasons: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))

    model: str
    read_file: bool = Field(default=False)

    created_at: datetime = Field(default_factory=utcnow, sa_column=dt_column(nullable=False))
