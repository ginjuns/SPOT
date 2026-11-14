"""Pydantic 요청 모델."""
from typing import Literal, Optional

from pydantic import BaseModel, Field

AgeGroup = Literal["u19", "19_34", "35_49", "50_64", "65_74", "75plus"]
Gender = Literal["M", "F"]
Household = Literal[
    "single", "single_parent", "multi_child", "multicultural", "no_house",
    "nk_defector", "new_resident", "extended",
]
RegionCode = Field(default=None, pattern=r"^\d{2}(\d{3})?$")


class SearchRequest(BaseModel):
    age_group: Optional[AgeGroup] = None
    gender: Optional[Gender] = None
    region_code: Optional[str] = RegionCode
    household: Optional[Household] = None
    page: int = Field(default=1, ge=1, le=1000)
