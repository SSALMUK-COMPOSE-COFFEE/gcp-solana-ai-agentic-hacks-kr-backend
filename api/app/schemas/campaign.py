from datetime import datetime

from pydantic import Field

from app.schemas.base import CamelModel


class CategoryPolicy(CamelModel):
    max_unit_price: int | None = Field(default=None, gt=0)
    max_total: int | None = Field(default=None, gt=0)
    unit_label: str | None = Field(default=None, max_length=30)


class CampaignPolicy(CamelModel):
    categories: dict[str, CategoryPolicy] = Field(default_factory=dict)
    max_per_category: int | None = Field(default=None, gt=0)
    allow_surplus_scaling: bool = False
    ai_review_budget: int | None = Field(default=None, gt=0)

    def to_stored(self) -> dict:
        return self.model_dump(by_alias=True, exclude_none=True)


class CreateCampaignRequest(CamelModel):
    title: str = Field(min_length=1, max_length=100)
    category: str = Field(min_length=1, max_length=50)
    goal_amount: int = Field(gt=0)
    deadline: datetime
    policy: CampaignPolicy = Field(default_factory=CampaignPolicy)


class UpdateCampaignRequest(CamelModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    deadline: datetime | None = None
    policy: CampaignPolicy | None = None


class CreateTierRequest(CamelModel):
    title: str = Field(min_length=1, max_length=100)
    price: int = Field(gt=0)
    items: list[str] = Field(min_length=1, max_length=20)
    limit: int | None = Field(default=None, ge=1)
