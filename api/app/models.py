from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Integer,
    String,
    text,
)
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _dt(**kw) -> Column:
    return Column(DateTime(timezone=True), **kw)


def _amount(**kw) -> Column:
    return Column(BigInteger, nullable=False, **kw)


def _amount_zero() -> Column:
    return Column(BigInteger, nullable=False, default=0, server_default="0")


def _int_zero() -> Column:
    return Column(Integer, nullable=False, default=0, server_default="0")


def _bool_false() -> Column:
    return Column(Boolean, nullable=False, default=False, server_default=text("false"))


class CampaignStatus:
    FUNDING = "모금중"
    EXECUTING = "집행중"
    REFUNDING = "환불중"
    CLOSED = "종료"

    ALL = (FUNDING, EXECUTING, REFUNDING, CLOSED)


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
    created_at: datetime = Field(default_factory=utcnow, sa_column=_dt(nullable=False))


class WalletNonce(SQLModel, table=True):
    __tablename__ = "wallet_nonces"

    id: int | None = Field(default=None, primary_key=True)
    wallet_address: str = Field(index=True)
    nonce: str = Field(sa_column=Column(String(128), unique=True, nullable=False, index=True))
    used: bool = Field(default=False, sa_column=_bool_false())
    expires_at: datetime = Field(sa_column=_dt(nullable=False))


class RevokedToken(SQLModel, table=True):
    __tablename__ = "revoked_tokens"

    jti: str = Field(primary_key=True, max_length=64)
    expires_at: datetime = Field(sa_column=_dt(nullable=False))


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

    goal_amount: int = Field(sa_column=_amount())
    raised_amount: int = Field(default=0, sa_column=_amount_zero())
    released_amount: int = Field(default=0, sa_column=_amount_zero())
    refunded_amount: int = Field(default=0, sa_column=_amount_zero())
    contributor_count: int = Field(default=0, sa_column=_int_zero())
    refunded_count: int = Field(default=0, sa_column=_int_zero())

    deadline: datetime = Field(sa_column=_dt(nullable=False, index=True))
    status: str = Field(default=CampaignStatus.FUNDING, index=True)

    owner_id: int = Field(foreign_key="users.id", index=True)
    authority_wallet: str

    campaign_pda: str | None = None
    escrow_pda: str | None = None

    created_at: datetime = Field(default_factory=utcnow, sa_column=_dt(nullable=False))


class Contribution(SQLModel, table=True):
    __tablename__ = "contributions"

    id: int | None = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="campaigns.id", index=True)
    user_id: int | None = Field(default=None, foreign_key="users.id", index=True)
    wallet_address: str = Field(index=True)
    amount: int = Field(sa_column=_amount())
    reference: str | None = Field(default=None, index=True)
    tx_signature: str | None = Field(
        default=None, sa_column=Column(String(128), unique=True, nullable=True)
    )
    refunded: bool = Field(default=False, sa_column=_bool_false())
    created_at: datetime = Field(default_factory=utcnow, sa_column=_dt(nullable=False))


class Certificate(SQLModel, table=True):
    __tablename__ = "certificates"

    id: int | None = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="campaigns.id", index=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    contribution_id: int = Field(foreign_key="contributions.id", unique=True)
    mint_address: str = Field(sa_column=Column(String(64), unique=True, nullable=False))
    image_url: str | None = None
    issued_at: datetime = Field(default_factory=utcnow, sa_column=_dt(nullable=False))
