from datetime import datetime

from sqlalchemy import Column, String
from sqlmodel import Field, SQLModel

from app.models.base import bool_false_column, dt_column


class WalletNonce(SQLModel, table=True):
    __tablename__ = "wallet_nonces"

    id: int | None = Field(default=None, primary_key=True)
    wallet_address: str = Field(index=True)
    nonce: str = Field(sa_column=Column(String(128), unique=True, nullable=False, index=True))
    used: bool = Field(default=False, sa_column=bool_false_column())
    expires_at: datetime = Field(sa_column=dt_column(nullable=False))


class RevokedToken(SQLModel, table=True):
    __tablename__ = "revoked_tokens"

    jti: str = Field(primary_key=True, max_length=64)
    expires_at: datetime = Field(sa_column=dt_column(nullable=False))
