"""POST /api/search — 버튼 조건 조회 (LLM 사용 안 함)."""
from fastapi import APIRouter

from app.models import SearchRequest
from app.services import retriever

router = APIRouter(prefix="/api")


@router.post("/search")
def search(req: SearchRequest):
    return retriever.search_by_conditions(
        req.age_group, req.gender, req.region_code, req.household, req.page
    )
