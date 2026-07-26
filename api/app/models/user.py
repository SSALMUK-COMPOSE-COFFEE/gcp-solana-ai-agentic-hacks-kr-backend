from datetime import datetime

from sqlalchemy import Column, String
from sqlmodel import Field, SQLModel

from app.models.base import dt_column, utcnow


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(sa_column=Column(String(255), unique=True, nullable=False, index=True))
    password_hash: str
    name: str
    bio: str | None = None
    avatar_url: str | None = None
    wallet_address: str | None = Field(
        default=None, sa_column=Column(String(64), unique=True, nullable=True, index=True)
    )
    created_at: datetime = Field(default_factory=utcnow, sa_column=dt_column(nullable=False))
