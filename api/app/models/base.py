from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, text


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def dt_column(**kw) -> Column:
    return Column(DateTime(timezone=True), **kw)


def amount_column(**kw) -> Column:
    return Column(BigInteger, nullable=False, **kw)


def amount_zero_column() -> Column:
    return Column(BigInteger, nullable=False, default=0, server_default="0")


def int_zero_column() -> Column:
    return Column(Integer, nullable=False, default=0, server_default="0")


def bool_false_column() -> Column:
    return Column(Boolean, nullable=False, default=False, server_default=text("false"))
