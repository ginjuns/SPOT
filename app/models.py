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


class Conditions(BaseModel):
    """지금까지 정해진 조건. need 와 search_text 는 서버가 준 값을 브라우저가 그대로 돌려보낸다."""
    age_group: Optional[AgeGroup] = None
    gender: Optional[Gender] = None
    region_code: Optional[str] = RegionCode
    household: Optional[Household] = None
    for_child: Optional[bool] = None   # 아이를 위한 지원을 묻는 질문인지 (서버가 분석해서 준 값)
    need: Optional[str] = Field(default=None, max_length=20)
    search_text: Optional[str] = Field(default=None, max_length=600)


class HistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=2000)


class ChatRequest(BaseModel):
    # 글자 수(300자)는 쉬운 안내 문구로 답하려고 라우터에서 직접 검사한다.
    message: str = Field(default="", max_length=5000)
    conditions: Conditions = Conditions()
    history: list[HistoryItem] = Field(default=[], max_length=50)
    asked: bool = False


class SearchRequest(BaseModel):
    age_group: Optional[AgeGroup] = None
    gender: Optional[Gender] = None
    region_code: Optional[str] = RegionCode
    household: Optional[Household] = None
    page: int = Field(default=1, ge=1, le=1000)
