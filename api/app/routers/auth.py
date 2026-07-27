from datetime import timedelta

import jwt
from fastapi import APIRouter, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.core import security
from app.core.config import settings
from app.core.deps import CurrentUser, SessionDep
from app.models import RevokedToken, User, WalletNonce, utcnow
from app.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    SignupRequest,
    WalletNonceRequest,
    WalletVerifyRequest,
)

router = APIRouter(prefix="/auth", tags=["auth"])

INVALID_CREDENTIALS = "이메일 또는 비밀번호가 올바르지 않습니다."
INVALID_REFRESH = "만료되었거나 식별할 수 없는 토큰"
INVALID_WALLET = "유효하지 않은 지갑 주소입니다."
INVALID_NONCE = "nonce가 만료되었거나 일치하지 않습니다."
INVALID_SIGNATURE = "서명 검증에 실패했습니다."
WALLET_TAKEN = "이미 다른 계정에 연결된 지갑입니다."
WALLET_NOT_LINKED = "해당 지갑으로 연결된 계정이 없습니다."


def _token_pair(user_id: int) -> dict[str, str]:
    return {
        "accessToken": security.create_access_token(user_id),
        "refreshToken": security.create_refresh_token(user_id),
    }


@router.post("/signup", status_code=201)
async def signup(body: SignupRequest, session: SessionDep) -> dict:
    user = User(
        email=body.email.lower(),
        password_hash=security.hash_password(body.password),
        name=body.name,
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="이미 사용 중인 이메일입니다.") from None

    await session.refresh(user)
    return {
        **_token_pair(user.id),
        "user": {"id": user.id, "name": user.name, "email": user.email},
    }


@router.post("/login")
async def login(body: LoginRequest, session: SessionDep) -> dict:
    result = await session.exec(select(User).where(User.email == body.email.lower()))
    user = result.first()
    if user is None or not security.verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail=INVALID_CREDENTIALS)
    return _token_pair(user.id)


@router.post("/refresh")
async def refresh(body: RefreshRequest, session: SessionDep) -> dict:
    try:
        payload = security.decode_token(body.refresh_token, security.REFRESH)
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail=INVALID_REFRESH) from None

    if await session.get(RevokedToken, payload["jti"]):
        raise HTTPException(status_code=401, detail=INVALID_REFRESH)

    user = await session.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(status_code=401, detail=INVALID_REFRESH)

    return {"accessToken": security.create_access_token(user.id)}


@router.post("/logout")
async def logout(body: LogoutRequest, user: CurrentUser, session: SessionDep) -> dict:
    try:
        payload = security.decode_token(body.refresh_token, security.REFRESH)
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token.") from None

    if payload["sub"] != str(user.id):
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    if not await session.get(RevokedToken, payload["jti"]):
        session.add(
            RevokedToken(jti=payload["jti"], expires_at=security.token_expires_at(payload))
        )
        await session.commit()

    return {"message": "로그아웃되었습니다."}


async def _consume_nonce(session, body: WalletVerifyRequest) -> None:
    result = await session.exec(
        select(WalletNonce).where(
            WalletNonce.nonce == body.nonce,
            WalletNonce.wallet_address == body.wallet_address,
        )
    )
    record = result.first()
    if record is None or record.used or record.expires_at <= utcnow():
        raise HTTPException(status_code=400, detail=INVALID_NONCE)

    if not security.verify_wallet_signature(body.wallet_address, body.nonce, body.signature):
        raise HTTPException(status_code=401, detail=INVALID_SIGNATURE)

    record.used = True
    session.add(record)


@router.post("/wallet/nonce")
async def wallet_nonce(body: WalletNonceRequest, session: SessionDep) -> dict:
    if not security.is_valid_wallet(body.wallet_address):
        raise HTTPException(status_code=400, detail=INVALID_WALLET)

    record = WalletNonce(
        wallet_address=body.wallet_address,
        nonce=security.create_wallet_nonce(),
        expires_at=utcnow() + timedelta(seconds=settings.nonce_ttl),
    )
    session.add(record)
    await session.commit()

    return {"nonce": record.nonce}


@router.post("/wallet/connect")
async def wallet_connect(
    body: WalletVerifyRequest, user: CurrentUser, session: SessionDep
) -> dict:
    await _consume_nonce(session, body)

    result = await session.exec(select(User).where(User.wallet_address == body.wallet_address))
    holder = result.first()
    if holder is not None and holder.id != user.id:
        raise HTTPException(status_code=409, detail=WALLET_TAKEN)

    user.wallet_address = body.wallet_address
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail=WALLET_TAKEN) from None

    return {"message": "지갑이 연결되었습니다.", "walletAddress": user.wallet_address}


@router.post("/wallet/login")
async def wallet_login(body: WalletVerifyRequest, session: SessionDep) -> dict:
    await _consume_nonce(session, body)

    result = await session.exec(select(User).where(User.wallet_address == body.wallet_address))
    user = result.first()
    if user is None:
        raise HTTPException(status_code=401, detail=WALLET_NOT_LINKED)

    await session.commit()

    return {**_token_pair(user.id), "walletAddress": user.wallet_address}
