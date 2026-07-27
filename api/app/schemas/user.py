from pydantic import Field

from app.schemas.base import CamelModel


class UpdateProfileRequest(CamelModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    bio: str | None = Field(default=None, max_length=200)
    avatar_url: str | None = Field(default=None, max_length=500)
