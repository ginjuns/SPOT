"""GET /api/options, GET /api/regions, GET /api/health"""
import json

from fastapi import APIRouter, Query

from app import config, db

router = APIRouter(prefix="/api")

OPTIONS = json.loads((config.DATA_DIR / "options.json").read_text(encoding="utf-8"))


@router.get("/options")
def options():
    sido = db.query("SELECT code, sido AS name FROM region WHERE sigungu IS NULL ORDER BY sido")
    return {**OPTIONS, "sido": sido}


@router.get("/regions")
def regions(sido: str = Query(pattern=r"^\d{2}$")):
    """한 시·도의 시·군·구 목록. 세종·제주처럼 시·군·구가 없으면 빈 목록."""
    rows = db.query(
        "SELECT code, sigungu AS name FROM region "
        "WHERE sigungu IS NOT NULL AND LEFT(code, 2) = %s ORDER BY sigungu",
        (sido,),
    )
    return {"regions": rows}


@router.get("/health")
def health():
    row = db.query("SELECT count(*) AS n, max(collected_at) AS d FROM policy")[0]
    return {"status": "ok", "policy_count": row["n"], "data_date": row["d"]}
