from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, Column, String
from sqlmodel import Field, SQLModel

from app.models.base import amount_column, dt_column, utcnow


class ProofType:
    QUOTE = "quote"
    RECEIPT = "receipt"

    ALL = (QUOTE, RECEIPT)


class ProofStatus:
    PENDING = "검토중"
    APPROVED = "승인"
    REJECTED = "거절"

    ALL = (PENDING, APPROVED, REJECTED)


class Proof(SQLModel, table=True):
    __tablename__ = "proofs"
    __table_args__ = (
        CheckConstraint("type IN ('quote', 'receipt')", name="ck_proofs_type"),
        CheckConstraint(
            "status IN ('검토중', '승인', '거절')",
            name="ck_proofs_status",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="campaigns.id", index=True)
    vendor_id: int | None = Field(default=None, foreign_key="vendors.id", index=True)

    type: str = Field(index=True)
    amount: int = Field(sa_column=amount_column())
    items: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    file_url: str | None = None

    status: str = Field(default=ProofStatus.PENDING, index=True)
    release_tx: str | None = Field(
        default=None, sa_column=Column(String(128), unique=True, nullable=True)
    )

    created_at: datetime = Field(default_factory=utcnow, sa_column=dt_column(nullable=False))
