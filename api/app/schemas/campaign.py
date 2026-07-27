from datetime import datetime

from pydantic import Field

from app.schemas.base import CamelModel


class CreateCampaignRequest(CamelModel):
    title: str = Field(min_length=1, max_length=100)
    category: str = Field(min_length=1, max_length=50)
    goal_amount: int = Field(gt=0)
    deadline: datetime
    policy: dict = Field(default_factory=dict)


class UpdateCampaignRequest(CamelModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    deadline: datetime | None = None
