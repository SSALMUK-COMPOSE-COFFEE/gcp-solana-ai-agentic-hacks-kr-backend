import jwt
from fastapi import APIRouter, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app import security
from app.deps import CurrentUser, SessionDep
from app.models import RevokedToken, User
from app.schemas import LoginRequest, LogoutRequest, RefreshRequest, SignupRequest

router = APIRouter(prefix="/auth", tags=["auth"])

INVALID_CREDENTIALS = "이메일 또는 비밀번호가 올바르지 않습니다."
INVALID_REFRESH = "만료되었거나 식별할 수 없는 토큰"


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
