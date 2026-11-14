"""GET /api/policy/{id}, GET /api/policies?ids=..."""
from fastapi import APIRouter, HTTPException

from app import db
from app.services import retriever

router = APIRouter(prefix="/api")

DETAIL_COLUMNS = (
    "id, name, agency, category, summary, target, criteria, content, how_to_apply, "
    "apply_place, contact, url, has_income_rule, collected_at"
)
MAX_IDS = 10


@router.get("/policy/{policy_id}")
def get_policy(policy_id: str):
    rows = db.query(f"SELECT {DETAIL_COLUMNS} FROM policy WHERE id = %s", (policy_id,))
    if not rows:
        raise HTTPException(404, "정책을 찾지 못했어요. 주소를 다시 확인해 주세요.")
    return rows[0]


@router.get("/policies")
def get_policies(ids: str):
    """공유 링크 화면용. 보낸 순서대로 카드 목록을 돌려준다."""
    id_list = [i.strip() for i in ids.split(",") if i.strip()][:MAX_IDS]
    rows = db.query(
        f"SELECT {retriever.CARD_COLUMNS} FROM policy WHERE id = ANY(%s)", (id_list,)
    )
    by_id = {r["id"]: r for r in rows}
    return {"policies": [retriever.to_card(by_id[i]) for i in id_list if i in by_id]}
