from datetime import datetime

from sqlalchemy import Column, String
from sqlmodel import Field, SQLModel

from app.models.base import bool_false_column, dt_column, utcnow


class Vendor(SQLModel, table=True):
    __tablename__ = "vendors"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    wallet_address: str = Field(
        sa_column=Column(String(64), unique=True, nullable=False, index=True)
    )
    category: str = Field(index=True)
    contact: str | None = None

    allowlisted: bool = Field(default=False, sa_column=bool_false_column())
    api_key_hash: str = Field(sa_column=Column(String(64), unique=True, nullable=False))

    created_at: datetime = Field(default_factory=utcnow, sa_column=dt_column(nullable=False))
