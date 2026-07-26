from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

from app import security
from app.config import settings
from app.db import get_session
from app.models import User

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


async def require_service_token(
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="인증이 필요합니다.")
    if authorization.removeprefix("Bearer ").strip() != settings.service_token:
        raise HTTPException(status_code=401, detail="인증이 필요합니다.")


ServiceToken = Annotated[None, Depends(require_service_token)]
