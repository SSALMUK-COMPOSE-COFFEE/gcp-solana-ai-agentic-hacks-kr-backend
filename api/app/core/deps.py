import secrets
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import security
from app.core.config import settings
from app.core.db import get_session
from app.models import User, Vendor

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return authorization.removeprefix("Bearer ").strip()


async def get_current_user(
    session: SessionDep,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    token = _bearer(authorization)
    try:
        payload = security.decode_token(token, security.ACCESS)
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.") from None

    user = await session.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def _is_service_token(token: str) -> bool:
    return bool(settings.service_token) and secrets.compare_digest(
        token, settings.service_token
    )


async def require_service_token(
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="인증이 필요합니다.")
    if not _is_service_token(authorization.removeprefix("Bearer ").strip()):
        raise HTTPException(status_code=401, detail="인증이 필요합니다.")


ServiceToken = Annotated[None, Depends(require_service_token)]


async def get_agent_caller(
    session: SessionDep,
    authorization: Annotated[str | None, Header()] = None,
) -> User | None:
    token = _bearer(authorization)
    if _is_service_token(token):
        return None

    try:
        payload = security.decode_token(token, security.ACCESS)
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="인증이 필요합니다.") from None

    user = await session.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(status_code=401, detail="인증이 필요합니다.")
    return user


AgentCaller = Annotated[User | None, Depends(get_agent_caller)]


async def get_vendor(
    session: SessionDep,
    x_vendor_key: Annotated[str | None, Header()] = None,
) -> Vendor:
    if not x_vendor_key:
        raise HTTPException(status_code=401, detail="벤더 인증이 필요합니다.")

    result = await session.exec(
        select(Vendor).where(Vendor.api_key_hash == security.hash_api_key(x_vendor_key))
    )
    vendor = result.first()
    if vendor is None:
        raise HTTPException(status_code=401, detail="벤더 인증이 필요합니다.")
    return vendor


CurrentVendor = Annotated[Vendor, Depends(get_vendor)]
