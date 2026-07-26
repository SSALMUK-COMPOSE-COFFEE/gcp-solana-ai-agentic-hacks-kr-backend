from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from pydantic.alias_generators import to_camel

from app.security import PASSWORD_MAX_BYTES


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class SignupRequest(CamelModel):
    email: EmailStr
    password: str = Field(min_length=8)
    name: str = Field(min_length=1, max_length=50)

    @field_validator("password")
    @classmethod
    def password_fits_bcrypt(cls, v: str) -> str:
        if len(v.encode()) > PASSWORD_MAX_BYTES:
            raise ValueError("password too long")
        return v


class LoginRequest(CamelModel):
    email: EmailStr
    password: str


class RefreshRequest(CamelModel):
    refresh_token: str


class LogoutRequest(CamelModel):
    refresh_token: str
