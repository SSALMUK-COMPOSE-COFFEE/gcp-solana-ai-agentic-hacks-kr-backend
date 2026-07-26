from datetime import datetime

from sqlalchemy import Column, String
from sqlmodel import Field, SQLModel

from app.models.base import amount_column, bool_false_column, dt_column, utcnow


class Contribution(SQLModel, table=True):
    __tablename__ = "contributions"

    id: int | None = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="campaigns.id", index=True)
    user_id: int | None = Field(default=None, foreign_key="users.id", index=True)
    wallet_address: str = Field(index=True)
    amount: int = Field(sa_column=amount_column())
    reference: str | None = Field(default=None, index=True)
    tx_signature: str | None = Field(
        default=None, sa_column=Column(String(128), unique=True, nullable=True)
    )
    refunded: bool = Field(default=False, sa_column=bool_false_column())
    created_at: datetime = Field(default_factory=utcnow, sa_column=dt_column(nullable=False))


class Certificate(SQLModel, table=True):
    __tablename__ = "certificates"

    id: int | None = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="campaigns.id", index=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    contribution_id: int = Field(foreign_key="contributions.id", unique=True)
    mint_address: str = Field(sa_column=Column(String(64), unique=True, nullable=False))
    image_url: str | None = None
    issued_at: datetime = Field(default_factory=utcnow, sa_column=dt_column(nullable=False))
