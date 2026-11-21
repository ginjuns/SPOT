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
# 2026-11-14 Groq 모델 목록(API)으로 확인: llama 계열은 더 이상 제공되지 않는다.
# 무료 한도(2026-11-14 응답 헤더로 확인): 모델마다 하루 1,000회, 분당 8,000토큰.
# 답변 1번에 약 2,000토큰, 분석 1번에 약 1,200토큰을 쓴다.
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")           # 답변 생성용
GROQ_MODEL_ANALYZE = os.getenv("GROQ_MODEL_ANALYZE", "openai/gpt-oss-20b")  # 질문 분석용
# 답변용 모델이 분당 한도(모델마다 따로 8,000토큰)를 넘었을 때 대신 쓰는 모델. 비워 두면 쓰지 않는다.
GROQ_MODEL_BACKUP = os.getenv("GROQ_MODEL_BACKUP", "qwen/qwen3.8-27b")
# 생각(추론) 단계를 짧게 해서 토큰과 시간을 아낀다. 이 옵션이 없는 모델을 쓸 때는 빈 값으로 둔다.
GROQ_REASONING_EFFORT = os.getenv("GROQ_REASONING_EFFORT", "low")

# multilingual-e5-small 의 ONNX 판 (Hugging Face Hub 저장소 이름과 그 안의 파일)
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "Xenova/multilingual-e5-small")
EMBEDDING_MODEL_FILE = os.getenv("EMBEDDING_MODEL_FILE", "onnx/model_quantized.onnx")
# 무료 서버는 CPU가 작으므로 서버에서는 1로 둔다. 수집할 때는 PC 코어 수만큼 올리면 빠르다.
EMBEDDING_THREADS = int(os.getenv("EMBEDDING_THREADS", "1"))

DAILY_CHAT_LIMIT = int(os.getenv("DAILY_CHAT_LIMIT", "30"))
GLOBAL_DAILY_CHAT_LIMIT = int(os.getenv("GLOBAL_DAILY_CHAT_LIMIT", "200"))
# 시나리오 평가(2026-11-14)로 정한 값: 맞는 정책은 0.08~0.15, 관계없는 질문의 후보는 0.15 이상이었다.
MAX_DISTANCE = float(os.getenv("MAX_DISTANCE", "0.15"))
# 이보다 가까운 후보가 있는데 답변 AI가 하나도 고르지 않으면 그 후보를 그대로 보여 준다 (맞는 정책은 0.08~0.15였다).
STRONG_DISTANCE = 0.10

# 메신저(텔레그램·디스코드)
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "")   # 배포 주소. 메신저 답의 [자세히 보기] 링크에 쓴다
MESSENGER_DAILY_LIMIT = int(os.getenv("MESSENGER_DAILY_LIMIT", "100"))   # 메신저마다 하루 질문 수
# 텔레그램. 둘 중 하나라도 비어 있으면 텔레그램 경로는 404를 돌려준다 (웹은 영향 없음).
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")   # setWebhook 의 secret_token
# 디스코드. 둘 중 하나라도 비어 있으면 디스코드 경로는 404를 돌려준다. 봇 토큰은 명령 등록 스크립트에서만 쓴다.
DISCORD_APPLICATION_ID = os.getenv("DISCORD_APPLICATION_ID", "")
DISCORD_PUBLIC_KEY = os.getenv("DISCORD_PUBLIC_KEY", "")   # 요청 서명 검사용
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
# 네이버 톡톡. 둘 중 하나라도 비어 있으면 네이버 톡톡 경로는 404를 돌려준다.
NAVERTALK_AUTH_KEY = os.getenv("NAVERTALK_AUTH_KEY", "")             # 파트너센터 > 챗봇 API 설정 > 보내기 API 인증 값
NAVERTALK_WEBHOOK_SECRET = os.getenv("NAVERTALK_WEBHOOK_SECRET", "")  # 웹훅 주소 끝에 붙이는 비밀 문자열
# 카카오톡 채널 챗봇. 비어 있으면 카카오 경로는 404를 돌려준다.
KAKAO_SKILL_SECRET = os.getenv("KAKAO_SKILL_SECRET", "")   # 오픈빌더 스킬 헤더값(X-Spot-Secret)에 넣는 비밀 문자열

# 답변 생성에 넣는 후보 정책 글(지원 대상·지원 내용)의 최대 글자 수
# 200자일 때 답변 1번에 3,000토큰을 써서 1분에 2번밖에 답하지 못했다. 120자로 줄였다.
CANDIDATE_TEXT_LIMIT = 120
