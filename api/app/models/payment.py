from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, Column, String
from sqlmodel import Field, SQLModel

from app.models.base import (
    amount_column,
    amount_zero_column,
    bool_false_column,
    dt_column,
    utcnow,
)


class PaymentStatus:
    PENDING = "pending"
    CONFIRMED = "confirmed"

    ALL = (PENDING, CONFIRMED)


class PaymentRequest(SQLModel, table=True):
    __tablename__ = "payment_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'confirmed')",
            name="ck_payment_requests_status",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    reference: str = Field(sa_column=Column(String(64), unique=True, nullable=False, index=True))

    campaign_id: int = Field(foreign_key="campaigns.id", index=True)
    user_id: int | None = Field(default=None, foreign_key="users.id", index=True)
    tier_id: int | None = Field(default=None, foreign_key="reward_tiers.id")
    amount: int = Field(sa_column=amount_column())

    status: str = Field(default=PaymentStatus.PENDING, index=True)
    contributor_wallet: str | None = Field(default=None, index=True)
    tx_signature: str | None = Field(
        default=None, sa_column=Column(String(128), unique=True, nullable=True)
    )

    created_at: datetime = Field(default_factory=utcnow, sa_column=dt_column(nullable=False))


class MicropayRail:
    PAYSH = "paysh"
    X402 = "x402"


class Micropay(SQLModel, table=True):
    __tablename__ = "micropays"

    id: int | None = Field(default=None, primary_key=True)
    campaign_id: int | None = Field(default=None, foreign_key="campaigns.id", index=True)
    resource: str = Field(index=True)
    amount: int = Field(sa_column=amount_zero_column())
    paid: bool = Field(default=False, sa_column=bool_false_column())
    tx_signature: str | None = Field(
        default=None, sa_column=Column(String(128), unique=True, nullable=True)
    )
    created_at: datetime = Field(default_factory=utcnow, sa_column=dt_column(nullable=False))

    rail: str = Field(default=MicropayRail.PAYSH, index=True)
    channel_id: str | None = Field(
        default=None, sa_column=Column(String(64), nullable=True, index=True)
    )
    authorized_amount: int | None = Field(
        default=None, sa_column=Column(BigInteger, nullable=True)
    )
    settled: bool = Field(default=False, sa_column=bool_false_column())
