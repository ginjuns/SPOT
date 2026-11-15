"""POST /api/search — 직접 찾기: 조건, 분야, 낱말 (LLM 사용 안 함)."""
from fastapi import APIRouter

from app.models import SearchRequest
from app.services import analyzer, retriever

router = APIRouter(prefix="/api")


@router.post("/search")
def search(req: SearchRequest):
    return retriever.search_by_conditions(
        req.age_group, req.gender, req.region_code, req.household, req.page,
        category=req.category, keyword=req.q, related=analyzer.related_names(req.q),
        include_org=req.include_org,
    )
