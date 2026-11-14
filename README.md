# SPOT

평소 말투로 상황을 이야기하면, 받을 수 있는 정부·지자체 지원 정책을 출처와 함께 알려 주는 모바일 웹앱입니다.
자세한 요구사항과 구조는 [PROJECT_SPEC.md](PROJECT_SPEC.md)에 있습니다.

## 현재 진행 상황

- [x] 1주차 1단계: 프로젝트 뼈대
- [x] 1주차 2단계: 테이블 생성 SQL 작성 (`scripts/init_db.sql`), Neon에 테이블 생성
- [x] 1주차 3단계: 공공데이터 API 응답 확인, 지원조건 코드 매핑표 (`data/condition_codes.json`)
- [x] 1주차 4단계: 수집 스크립트 (`scripts/ingest.py`)
- [x] 1주차 5단계: 지역 코드 (`scripts/load_regions.py`, `data/regions.csv`)
- [x] 1주차 6단계: 조회 API (`/api/search`, `/api/policy/{id}`, `/api/policies`, `/api/options`, `/api/regions`, `/api/health`)
- [x] 1주차 7단계: Render 첫 배포 (`/api/health` 확인 완료)
- [x] 2주차 1단계: 임베딩(`embedder.py`), 조건 필터 + 의미 검색(`retriever.py`의 `search_semantic`)
- [x] 2주차 2단계: Groq 연결(`llm.py`), 질문 분석(`analyzer.py`, `prompts/analyze.txt`, `data/keywords.json`)
- [x] 2주차 3단계: 되묻기 흐름 (`POST /api/chat`, 답변 생성은 3주차)
- [x] 2주차 4단계: 개인정보 가리기 (`privacy.py`) + 테스트
- [x] 2주차 5단계: 시나리오 질문 30개 (`data/scenarios.json`)
- [x] 2주차 6단계: 검색 평가 스크립트 (`scripts/eval_scenarios.py --no-llm`) — 30개 중 26개(87%), 거리 기준값 0.15로 결정
- [x] 2주차 7단계: 공통 CSS, 버튼 조회 화면(`search.html`), 정책 상세 화면(`policy.html`)
- [x] 3주차 1단계: 답변 생성(`answerer.py`), fallback 처리, 사용량 제한(`rate_limit.py`)
- [x] 3주차 2단계: 나머지 화면 (시작, 채팅, 공유, 주민센터에서 보여주기, 큰 글씨·고대비 모드)
- [ ] 3주차 3단계: PWA 설정 (홈 화면에 추가, 아이콘)

## 준비물 (모두 무료)

| 무엇 | 어디서 | `.env`에 넣을 이름 |
|---|---|---|
| 공공데이터포털 인증키 | data.go.kr → 「행정안전부_대한민국 공공서비스(혜택) 정보」 활용신청 | `DATA_GO_KR_API_KEY` |
| Neon DB 연결 문자열 | neon.tech → 프로젝트 만들기 → Connection string | `DATABASE_URL` |
| Groq API 키 | console.groq.com → API Keys | `GROQ_API_KEY` |

## 내 컴퓨터에서 실행하기 (Windows PowerShell)

```powershell
# 1. 가상환경 만들기 (처음 한 번)
python -m venv .venv
.venv\Scripts\Activate.ps1

# 2. 패키지 설치 (처음 한 번, 몇 분 걸림)
pip install -r requirements.txt

# 3. 환경변수 파일 만들기 (처음 한 번) → 메모장으로 .env 를 열어 값 채우기
Copy-Item .env.example .env

# 4. 서버 실행
uvicorn app.main:app --reload --port 7860
```

브라우저에서 http://localhost:7860 을 엽니다.

## DB 테이블 만들기

Neon 콘솔의 **SQL Editor**에 `scripts/init_db.sql` 내용을 붙여 넣고 실행합니다. 여러 번 실행해도 괜찮습니다.

## 정책 데이터 넣기

```powershell
# 1. 공공데이터 API에서 받아서 → 정리 → 임베딩 → DB 저장 (10~20분)
python scripts/ingest.py

# 2. 지역 코드표 갱신 후 DB에 넣기 (지역 이름이 바뀌었을 때만 --build)
python scripts/load_regions.py --build
python scripts/load_regions.py
```

- 받은 원본은 `data/raw/`에 남습니다. 정리 규칙만 고쳤을 때는 API를 다시 부르지 않고
  `python scripts/ingest.py --from-raw --no-embed` 로 빠르게 다시 만들 수 있습니다.
- `python scripts/ingest.py --from-raw --dry-run` 은 DB에 쓰지 않고 통계만 보여 줍니다.
- 지역 코드는 법정동 코드가 아니라 이 프로젝트에서 붙인 번호입니다 (시·도 2자리, 시·군·구 5자리).

## 배포하기 (Render 무료 웹 서비스)

1. 이 폴더를 GitHub 저장소에 올립니다.
2. render.com → **New → Web Service** → GitHub 저장소 연결 → Language **Docker**, Instance Type **Free**.
3. **Environment**에 `DATABASE_URL`(과 2주차부터 `GROQ_API_KEY`)을 넣습니다. Health Check Path는 `/api/health`.
4. 배포가 끝나면 `https://<서비스이름>.onrender.com/api/health` 가 `ok`를 돌려주는지 확인합니다.

- GitHub에 올릴(push) 때마다 자동으로 다시 배포됩니다.
- 무료 서비스는 15분쯤 접속이 없으면 잠들고, 깨어나는 데 1분쯤 걸립니다. **시연 전에 미리 접속해 둡니다.**

## 검색 평가

```powershell
# Groq를 쓰지 않고 검색만 평가 (몇 번이든 돌려도 됨)
python scripts/eval_scenarios.py --no-llm

# 실제 채팅처럼 질문 분석(작은 모델)을 거쳐서 평가 (5분쯤 걸림, Groq 한도 사용)
python scripts/eval_scenarios.py --no-llm --analyze
```

시나리오 30개(`data/scenarios.json`)의 기대 정책이 후보 8개 안에 드는 비율과 거리 분포를 보여 줍니다.

## 테스트

```powershell
python -m pytest -q
```

## 주의

- `.env` 파일은 절대 GitHub에 올리지 않습니다 (`.gitignore`에 들어 있음).
- 사용자의 대화 내용은 어디에도 저장하지 않습니다.
