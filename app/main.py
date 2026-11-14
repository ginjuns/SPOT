"""FastAPI 앱 생성, 라우터 등록, 정적 파일 제공."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import config, db
from app.routers import chat, meta, policy, search

logger = logging.getLogger("benefit")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
    logger.addHandler(_handler)


@asynccontextmanager
async def lifespan(app):
    db.open_pool()
    yield
    db.close_pool()


app = FastAPI(title="SPOT", docs_url=None, redoc_url=None, lifespan=lifespan)


# 오류 응답은 모두 {"error": "쉬운 문구"} 형태로 맞춘다.
@app.exception_handler(StarletteHTTPException)
async def http_error(request, exc):
    text = exc.detail if exc.status_code != 404 or exc.detail != "Not Found" else "찾으시는 화면이 없어요."
    return JSONResponse({"error": text}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return JSONResponse({"error": "고르신 내용을 다시 확인해 주세요."}, status_code=400)


@app.exception_handler(Exception)
async def server_error(request, exc):
    # 요청 본문은 남기지 않고 경로와 오류 종류만 남긴다.
    logger.error("%s %s", request.url.path, type(exc).__name__)
    return JSONResponse(
        {"error": "잠시 문제가 생겼어요. 조금 뒤에 다시 해 주세요."}, status_code=500
    )


app.include_router(chat.router)
app.include_router(search.router)
app.include_router(policy.router)
app.include_router(meta.router)

# 정적 파일은 API 라우터보다 뒤에 등록한다.
app.mount("/", StaticFiles(directory=config.WEB_DIR, html=True), name="web")
