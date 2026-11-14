"""환경변수 읽기. 비밀 값은 코드에 쓰지 않고 .env 에서만 읽는다."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

WEB_DIR = BASE_DIR / "web"
DATA_DIR = BASE_DIR / "data"

DATA_GO_KR_API_KEY = os.getenv("DATA_GO_KR_API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
# TODO(확인): Groq 콘솔에서 현재 제공 모델과 모델별 무료 한도 확인
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_MODEL_ANALYZE = os.getenv("GROQ_MODEL_ANALYZE", "llama-3.1-8b-instant")

# multilingual-e5-small 의 ONNX 판 (Hugging Face Hub 저장소 이름과 그 안의 파일)
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "Xenova/multilingual-e5-small")
EMBEDDING_MODEL_FILE = os.getenv("EMBEDDING_MODEL_FILE", "onnx/model_quantized.onnx")
# 무료 서버는 CPU가 작으므로 서버에서는 1로 둔다. 수집할 때는 PC 코어 수만큼 올리면 빠르다.
EMBEDDING_THREADS = int(os.getenv("EMBEDDING_THREADS", "1"))

DAILY_CHAT_LIMIT = int(os.getenv("DAILY_CHAT_LIMIT", "30"))
GLOBAL_DAILY_CHAT_LIMIT = int(os.getenv("GLOBAL_DAILY_CHAT_LIMIT", "200"))
MAX_DISTANCE = float(os.getenv("MAX_DISTANCE", "0.35"))

# 답변 생성에 넣는 후보 정책 글(지원 대상·지원 내용)의 최대 글자 수
CANDIDATE_TEXT_LIMIT = 200
