from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, Column, String
from sqlmodel import Field, SQLModel

from app.models.base import (
    amount_column,
    amount_zero_column,
    dt_column,
    int_zero_column,
    utcnow,
)


class CampaignStatus:
    FUNDING = "모금중"
    EXECUTING = "집행중"
    REFUNDING = "환불중"
    CLOSED = "종료"

    ALL = (FUNDING, EXECUTING, REFUNDING, CLOSED)


class Campaign(SQLModel, table=True):
    __tablename__ = "campaigns"
    __table_args__ = (
        CheckConstraint(
            "status IN ('모금중', '집행중', '환불중', '종료')",
            name="ck_campaigns_status",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    uuid: str = Field(sa_column=Column(String(36), unique=True, nullable=False, index=True))

    title: str
    category: str = Field(index=True)
    policy: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))

    goal_amount: int = Field(sa_column=amount_column())
    raised_amount: int = Field(default=0, sa_column=amount_zero_column())
    released_amount: int = Field(default=0, sa_column=amount_zero_column())
    refunded_amount: int = Field(default=0, sa_column=amount_zero_column())
    contributor_count: int = Field(default=0, sa_column=int_zero_column())
    refunded_count: int = Field(default=0, sa_column=int_zero_column())

    deadline: datetime = Field(sa_column=dt_column(nullable=False, index=True))
    status: str = Field(default=CampaignStatus.FUNDING, index=True)

    owner_id: int = Field(foreign_key="users.id", index=True)
    authority_wallet: str

    campaign_pda: str | None = None
    escrow_pda: str | None = None

    created_at: datetime = Field(default_factory=utcnow, sa_column=dt_column(nullable=False))


class RewardTier(SQLModel, table=True):
    __tablename__ = "reward_tiers"

    id: int | None = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="campaigns.id", index=True)

    title: str
    price: int = Field(sa_column=amount_column())
    items: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    limit: int | None = Field(default=None)
    sold_count: int = Field(default=0, sa_column=int_zero_column())

    created_at: datetime = Field(default_factory=utcnow, sa_column=dt_column(nullable=False))
