# 인수인계: SPOT AI 채팅을 텔레그램·디스코드에 붙이기

작성일: 2026-11-18 · 이 문서를 받은 AI가 처음부터 끝까지 읽고 시작한다.

## 1. 한 줄 요약

웹사이트(`web/`)는 그대로 두고, 웹의 [물어보기]와 **같은 AI 채팅 로직**을 텔레그램 봇과 디스코드 봇에서도 쓰게 만든다. 순서는 **텔레그램 → 디스코드**다. 네이버 톡톡·카카오톡은 이번 범위가 아니다 (8장에 조사 메모만 남긴다).

## 2. 시작 전에 반드시 지킬 것

### 먼저 읽을 파일
1. `CLAUDE.md` (짧다)
2. `PROJECT_SPEC.md` 전체. 특히 **0장 AI 작업 규칙**, 7장 `/api/chat`, 8장 AI 처리, 10장 개인정보
3. `app/routers/chat.py`, `app/services/rate_limit.py`, `app/services/privacy.py`, `app/models.py`, `app/config.py`

### 프로젝트 규칙 (명세서 0장 + 사용자가 따로 정한 것)
- 응답과 사용자에게 보이는 문구는 **쉬운 한국어**. 버튼 이름은 딱딱한 기능 이름 말고 말하듯이 쓴다 (예: "말로 묻기" ✗ → "물어보기" ○, "읽어 주기" ✗ → "소리로 듣기" ○).
- **비용 0원.** 유료 서비스·유료 요금제를 추가하지 않는다. 새 패키지는 무료 오픈소스만.
- **API 키·토큰은 코드에 쓰지 않는다.** `.env`로만 읽고, `.env.example`에는 변수 이름만 적는다.
- **사용자 대화 내용은 어디에도 저장하지 않는다** (DB, 파일, 로그). 로그에는 경로, 걸린 시간, 결과 유형(`ask/result/none/fallback`)만 남긴다.
- AI 답변은 **DB에서 검색된 정책만** 근거로 한다. 이 로직은 이미 `chat.py`와 `answerer.py`에 있으니 **새로 만들지 말고 그대로 재사용**한다.
- 확실하지 않은 외부 API 필드명은 추측으로 확정하지 말고 설정으로 빼고 `TODO(확인)` 주석을 단다.
- 명세서와 다르게 해야 할 이유가 생기면 **임의로 바꾸지 말고 사용자에게 먼저 묻는다.**
- 한 번에 한 단계씩 하고, 단계가 끝날 때마다 무엇을 만들었는지·어떻게 확인하는지 사용자에게 알린다.

### Git 규칙 (사용자가 정한 것, 꼭 지킬 것)
- 커밋 작성자는 **ginjuns 한 명만**. `Co-Authored-By` 같은 공동 작성자 줄을 **넣지 않는다.**
- 커밋 메시지는 한국어로 무엇을 했는지만 쓴다. **"2주차 2단계:" 같은 단계 표시와 `/api/chat` 같은 경로는 메시지에 넣지 않는다.**
- 단계가 끝나면 커밋하고 `git push origin main`까지 한다. 강제 push는 사용자 확인을 받는다.
- 화면 파일(`web/`)을 고치면 `web/service-worker.js`의 `CACHE` 버전 숫자를 올린다 (지금 `spot-v18`).
- 명세서(`PROJECT_SPEC.md`)도 바뀐 내용에 맞게 함께 고친다.

### 이 PC 환경 메모
- Windows, PowerShell. 전역 `python`에는 `pytest`가 설치돼 있지 않았다. 테스트 전에 가상환경이 있는지 확인하고, 없으면 사용자에게 물어본다.
- 배포: GitHub `main`에 올리면 Render(무료, Docker, 메모리 512MB)가 자동으로 다시 배포한다. 무료 서버는 15분쯤 접속이 없으면 잠들고, 깨어나는 데 1분쯤 걸린다.

## 3. 지금 상태 (2026-11-18, 커밋 `e2bd1c3` 기준)

- 웹은 모두 동작한다: 직접 찾기, 물어보기(AI 채팅), 정책 상세, 공유, 주민센터에서 보여주기, 글씨 크기 4단계, 말로 하기·소리로 듣기, 컴퓨터 화면 메뉴, "따뜻한 파스텔" 디자인.
- 메신저 관련 코드는 **아직 하나도 없다.**
- (2026-11-19) 5장 0단계 끝: 채팅 처리가 `app/services/chat_core.py`의 `handle`로 옮겨졌다. 빈 질문·300자 초과는 `{"type":"error","text"}`를 돌려주고, `routers/chat.py`가 400으로 바꾼다. 아래 설명의 `chat.py`는 이제 `chat_core.py`로 읽는다.
- (2026-11-19) 1단계 끝: `app/services/messenger.py` + `tests/test_messenger.py`. 연결 파일이 쓸 함수는 `start(플랫폼, 사용자ID)`, `on_text(플랫폼, 사용자ID, 글)`, `on_button(플랫폼, 사용자ID, 누름 코드)`이고, 셋 다 말 목록 `[{"text", "buttons": [[{"label","data"} 또는 {"label","url"}]]}]`을 돌려준다. 결과는 안내 문장 1개 + 정책마다 1개(링크 버튼 포함)로 나뉜다. 시·도는 16곳, 시·군·구는 한 시·도에 최대 31곳이다(`data/regions.csv` 기준, DB의 region 테이블과 같은 내용). 시·도를 고르면 우선 시·도 코드로 정해 두고, 시·군·구를 건너뛰면 시·도로 찾는다. 고른 조건과 "되물었음" 표시는 웹 채팅처럼 30분 동안 다음 질문에도 쓴다.

### 재사용할 채팅 로직 (`app/routers/chat.py`)
- `handle(req, client_key)`가 핵심이다. `ChatRequest`(message, conditions, history, asked)를 받아 아래 넷 중 하나를 돌려준다.
  - `{"type":"ask", "text", "ask":["age_group","region"], "conditions"}` — 나이대·지역이 없으면 되묻는다 (대화당 1번, `asked=True`면 다시 묻지 않음)
  - `{"type":"result", "text", "policies":[카드...], "conditions"}` — 카드: `id, name, agency, one_line, has_income_rule, url, collected_at, apply_period` 등 (`retriever.to_card` 참고)
  - `{"type":"none", "text", "conditions"}`
  - `{"type":"fallback", "text", "conditions"?}` — AI 한도 초과·오류. 웹은 버튼 찾기 화면으로 안내한다
- 400 오류는 `HTTPException`으로 던진다 (빈 질문, 300자 초과). **메신저에서 쓰려면 이 부분 때문에 리팩터링이 필요하다** (5장 0단계).
- 버튼으로 조건만 고른 다시 부르기는 `message=""`, `conditions.search_text` 있음, `asked=True`로 보낸다. 이때 AI 분석을 건너뛴다.
- 하루 한도: `rate_limit.check(key, is_question)`. 사용자별 30회, 전체 200회(환경변수). 사용자 키는 해시 값이다.
- 개인정보 가리기: `privacy.mask(text)` → (가린 글, 가렸는지). `handle` 안에서 이미 한다.

### 선택지 데이터
- 나이대 6개·성별·가구 형태·분야: `data/options.json` (`/api/options`가 시·도 목록을 붙여 준다).
- 시·군·구: `GET /api/regions?sido=11`. **한 시·도에 시·군·구가 최대 32개**(코드 앞 2자리 `12`)다. 디스코드 선택 메뉴는 25개가 한도라 나눠야 한다.

## 4. 설계 (정해진 것)

```
텔레그램 ──웹훅──▶ /api/telegram/webhook ┐
                                          ├─▶ messenger.py (공통) ─▶ chat_core.handle(...) ─▶ 검색·AI·검증 (기존)
디스코드 ──HTTP──▶ /api/discord/interactions┘        │
                                                    └─ 조건만 잠깐 기억 (메모리, 30분)
```

### 4-1. 대화 상태: "조건만, 메모리에, 잠깐"
- 웹은 조건을 브라우저가 들고 다니지만 메신저에는 브라우저가 없다. 그래서 서버가 **사용자별 조건만** 잠깐 기억한다.
- 저장소: 프로세스 메모리의 dict. 키 = `sha256(salt + 플랫폼 + 사용자ID)` 앞 16자 (`rate_limit.client_key`처럼 salt는 실행마다 새로). 값 = `conditions`, `asked`, 남은 되묻기 항목, 만료 시각. **30분** 지나면 지운다. 서버가 재시작되면 사라져도 괜찮다.
- **대화 글(message, history)은 저장하지 않는다.** `handle`에는 `history=[]`로 넘긴다. "아까 말한 것" 같은 앞 대화 참조는 메신저에서는 안 되는 것으로 둔다.
- `/start`(텔레그램)나 새 `/물어보기`(디스코드)를 하면 그 사용자의 조건을 지운다. "처음부터" 버튼도 둔다.

### 4-2. 하루 한도
- 메신저 사용자 키로 `rate_limit.check`를 그대로 쓴다 (웹과 Groq 한도를 함께 쓴다).
- 플랫폼별 하루 상한을 따로 둔다: `MESSENGER_DAILY_LIMIT` (기본 100). 넘으면 "오늘은 메신저 질문을 다 썼어요. 웹에서 직접 찾아보세요 + 링크".

### 4-3. 답 보여 주기 (두 플랫폼 공통 규칙)
- `result`: 안내 문장 + 정책 최대 5개. 각 정책은 이름, 기관, 한 줄 요약, "소득 기준 있음"(해당 시), **[자세히 보기]** = `{PUBLIC_BASE_URL}/policy.html?id=...`, [원문 보기] = 카드의 `url`, 자료 기준일. 맨 끝에 "자격은 신청하는 곳에서 최종 확인해 주세요."
- 카드 내용은 DB 값 그대로 쓴다. AI가 쓴 것은 `one_line`뿐이다.
- `ask`: 나이대 6개 + [잘 모르겠어요 / 건너뛰기] → 시·도 → 시·군·구 (+ 건너뛰기). 다 고르면 `message=""`, `asked=True`로 `handle`을 다시 부른다.
- `none`: 기존 문구 그대로 (주민센터, 129 안내).
- `fallback`: 문구 + 웹 직접 찾기 링크 `{PUBLIC_BASE_URL}/search.html?result=1&age_group=...&region_code=...`.
- 개인정보 안내: 처음 인사에 "이름이나 전화번호는 적지 않으셔도 돼요. 대화는 이 메신저 회사 서버에 남을 수 있어요." 를 넣는다.

### 4-4. 텔레그램
- **웹훅 방식** (`setWebhook`). 롱 폴링은 무료 서버가 잠들어서 쓰지 않는다.
- 경로: `POST /api/telegram/webhook`. `setWebhook`의 `secret_token`을 정하고, 요청 헤더 `X-Telegram-Bot-Api-Secret-Token`이 같은지 검사한다. 다르면 403.
- 받자마자 200을 돌려주고, 실제 처리는 FastAPI `BackgroundTasks`로 한다. 답은 `httpx`로 `sendMessage`를 부른다 (이미 `requirements.txt`에 있음).
- 같은 `update_id`가 다시 오면 무시한다 (메모리에 최근 것만, 잠든 서버가 깰 때 다시 보낼 수 있다).
- 되묻기 버튼 = 인라인 키보드. **`callback_data`는 64바이트까지**라서 짧은 코드로 쓴다: `a:65_74`, `a:-`(건너뛰기), `s:11`, `g:11680`, `g:-`, `r`(처음부터). 누르면 `answerCallbackQuery`를 꼭 부른다.
- 명령: `/start`(인사 + 예시 질문), `/reset`(처음부터). 그 밖의 글은 모두 질문으로 본다.
- 웹훅 등록은 `scripts/set_telegram_webhook.py`로 한다 (사용자가 한 번 실행).

### 4-5. 디스코드
- **Interactions Endpoint(HTTP) 방식**으로 한다. 게이트웨이(웹소켓 상주) 봇은 무료 서버가 잠들면 끊기므로 쓰지 않는다. 그래서 일반 채팅 글을 읽는 봇이 아니라 **슬래시 명령** 봇이다: `/물어보기 질문:<글>` (+ `/처음부터`). 명령 이름에 한글이 되는지 등록할 때 확인하고, 안 되면 `/ask`에 한국어 설명을 붙인다 (`TODO(확인)`).
- 경로: `POST /api/discord/interactions`. 요청마다 헤더 `X-Signature-Ed25519`, `X-Signature-Timestamp`로 **서명을 검사**하고, 틀리면 401. 검사 라이브러리는 `PyNaCl`(무료)을 `requirements.txt`에 더한다. (그 파일은 **ASCII만** 쓴다. 한국어 Windows의 pip가 한글 주석에서 실패한다.)
- PING(type 1)에는 `{"type":1}`로 답한다.
- **3초 안에 첫 응답**을 해야 한다. 명령에는 바로 "생각 중"(type 5, 나중에 답함)으로 응답하고, 처리 후 `PATCH /webhooks/{application_id}/{token}/messages/@original`로 답을 채운다 (토큰은 15분 유효).
- 되묻기 = 선택 메뉴(select). 메뉴 하나에 25개까지라서, 시·군·구가 25개를 넘으면 두 메뉴로 나눈다. 버튼·메뉴 누름(type 3)에는 type 6(나중에 메시지 수정)으로 응답한 뒤 같은 방식으로 수정한다.
- 명령 등록은 `scripts/register_discord_commands.py`로 한다 (사용자가 한 번 실행, 봇 토큰 사용).
- 알려진 한계: 서버가 잠들어 있으면 3초 안에 깨지 못해 첫 명령이 실패한다. 이 문제를 어떻게 할지는 7장의 열린 질문이다.

### 4-6. 새 환경변수 (`.env.example`과 명세서 11장에 이름만 추가)
```
PUBLIC_BASE_URL=            # 배포 주소 (카드의 [자세히 보기] 링크에 씀)
MESSENGER_DAILY_LIMIT=100   # 메신저마다 하루 질문 수
TELEGRAM_BOT_TOKEN=         # BotFather에서 받은 토큰
TELEGRAM_WEBHOOK_SECRET=    # setWebhook 의 secret_token 으로 쓸 임의 문자열
DISCORD_APPLICATION_ID=     # Developer Portal 의 Application ID
DISCORD_PUBLIC_KEY=         # 서명 검사용 Public Key
DISCORD_BOT_TOKEN=          # 명령 등록 스크립트에서만 씀 (서버에는 없어도 됨)
```
토큰이 비어 있으면 그 플랫폼 경로는 404를 돌려주고, 웹은 영향을 받지 않아야 한다.

## 5. 작업 순서와 완료 기준

| 단계 | 할 일 | 완료 기준 |
|---|---|---|
| 0. 리팩터링 | `chat.py`의 `handle` 로직을 `app/services/chat_core.py`로 옮긴다. `HTTPException` 대신 `{"type":"error","text":...}`를 돌려주고, 라우터가 그것을 400으로 바꾼다. 웹 동작은 바꾸지 않는다 | 기존 테스트(`tests/test_chat.py` 등) 모두 통과. 웹 채팅이 전과 같이 동작 |
| 1. 공통 처리 | `app/services/messenger.py`: 조건 기억(4-1), 하루 한도(4-2), 되묻기 순서, 결과를 플랫폼 중립 형태(글 + 버튼 목록)로 만들기(4-3) | `tests/test_messenger.py`: 조건 만료, 건너뛰기, 되묻기 순서, 카드 글 만들기, 한도 초과 |
| 2. 텔레그램 | `app/routers/telegram.py` + 웹훅 등록 스크립트 (4-4) | 실제 봇에서 질문 → 되묻기 버튼 → 결과까지 됨. 비밀 헤더가 틀리면 403 (테스트) |
| 3. 디스코드 | `app/routers/discord.py` + 명령 등록 스크립트 (4-5) | 실제 서버에서 `/물어보기` → 메뉴 → 결과. 서명이 틀리면 401 (테스트) |
| 4. 문서 | `PROJECT_SPEC.md`(새 절: 메신저, 10장 개인정보, 11장 환경변수), `README.md` 실행·등록 방법, 이 문서 갱신 | 사용자가 README만 보고 봇을 등록할 수 있음 |

각 단계가 끝나면 커밋하고 push한다 (2장 Git 규칙).

## 6. 사용자에게 받아야 하는 것 (필요한 단계에서 안내)

- 텔레그램: BotFather에서 `/newbot` → 봇 토큰. 비밀 문자열은 AI가 만들어 줘도 된다.
- 디스코드: Developer Portal에서 앱 생성 → Application ID, Public Key, Bot Token. 봇 초대 시 `applications.commands` 권한. 배포 후 "Interactions Endpoint URL"에 `{배포 주소}/api/discord/interactions`를 넣는다 (넣는 순간 디스코드가 PING으로 검사한다).
- Render 대시보드의 Environment에 4-6의 값 입력. **토큰은 사용자가 직접 넣는다.** AI는 값을 받아 코드나 문서에 적지 않는다.

## 7. 열린 질문 (사용자에게 물어서 정할 것)

1. **잠든 서버 문제**: 디스코드는 첫 응답 3초 제한 때문에 서버가 잠들어 있으면 실패한다. 무료 외부 서비스로 몇 분마다 `/api/health`를 불러 깨워 둘지(Render 무료 사용 시간 한도 안에서), 아니면 한계로 두고 "한 번 더 해 주세요" 안내만 할지.
2. 메신저에서도 앞 대화를 이어서 이해하게 할지 (지금 계획은 하지 않음. 하려면 대화 글을 잠깐 기억해야 해서 명세서 0장 4번 원칙과 부딪힌다).
3. 디스코드 명령 이름을 한글(`/물어보기`)로 할지 영어(`/ask`)로 할지.

## 8. 이번 범위 밖: 네이버 톡톡·카카오톡 조사 메모 (2026-11-18)

- **카카오톡**: (2026-11-21) 연결 파일을 만들었다. 아래 8-2 참고. 처음 조사 메모: 카카오톡 채널 + 카카오 i 오픈빌더 + 스킬 서버. 운영에 카카오 승인이 필요하다는 후기가 있다. 스킬 응답에 시간 제한(5초로 알려짐, 공식 수치는 확인 못 함)이 있어 AI 답변에는 **AI 챗봇 콜백**(`useCallback: true`, `callbackUrl`로 나중에 답)을 써야 한다. 콜백은 봇 테스트 화면에서는 제대로 안 되고 배포 후 시험해야 한다. 챗봇 요금 정책은 확인하지 못했다. [AI 챗봇 콜백 가이드](https://kakaobusiness.gitbook.io/main/tool/chatbot/skill_guide/ai_chatbot_callback_guide)
- **네이버 톡톡**: (2026-11-21) 연결 파일을 만들었다. 아래 8-1 참고.
- 4장의 `messenger.py` 공통 처리를 잘 만들어 두면, 나중에 이 둘은 연결 파일만 더하면 된다.

### 8-1. 네이버 톡톡 (2026-11-21, `app/routers/navertalk.py`, `tests/test_navertalk.py`)
- 문서: [navertalk/chatbot-api](https://github.com/navertalk/chatbot-api) README (2026-11-21 확인). 요금 이야기는 문서에 없다. 신청 화면에서 유료 항목이 있는지 사용자가 확인한다.
- 경로: `POST /api/navertalk/webhook/{NAVERTALK_WEBHOOK_SECRET}`. 네이버 톡톡은 **요청 서명을 주지 않는다**. 그래서 비밀 문자열을 주소 끝에 넣고, 틀리면 403을 돌려준다. 접속 기록(`uvicorn.access`)에는 비밀 문자열을 `***`로 가려 남긴다.
- 웹훅은 3초 안에 연결되고 5초 안에 답해야 한다. 그래서 본문 없이 200을 바로 돌려주고, 처리는 뒤에서 한 뒤 **보내기 API**(`POST https://gw.talk.naver.com/chatbot/v1/event`, 헤더 `Authorization: <인증 값>`)로 답한다. 처리하는 동안 `typingOn`을 보낸다.
- 이벤트: `open`(대화창 들어옴)이면 인사를 보낸다. `send`에서 `textContent.inputType == "button"`이고 `code`가 있으면 버튼 누름으로, 아니면 질문으로 처리한다. "처음부터"는 조건 지우기, "안내"는 인사로 처리한다. 사진 같은 다른 내용에는 "글로 적어 주세요"라고 답한다. `leave`, `friend`, `echo`에는 답하지 않는다 (`echo`에 답하면 끝없이 돈다).
- 버튼: `compositeContent`의 `TEXT` 버튼(`code`에 누름 코드)과 `LINK` 버튼을 쓴다. 메시지 하나에 버튼은 10개까지라서 시·도(17개)와 시·군·구(최대 32개)는 여러 메시지로 나눈다. 버튼 이름은 18자까지라서, 예시 질문처럼 긴 이름은 글에 전부 적고 버튼에는 앞부분만 쓴다. 버튼이 붙은 글은 1000자까지, 버튼 없는 글은 10000자까지다.
- 같은 이벤트를 두 번 보내는지, 버튼 누름에 이벤트 번호가 있는지는 문서에 없다. 그래서 텔레그램처럼 겹친 것을 거르는 일은 하지 않는다 (`TODO(확인)`: 실제 계정에서 확인).
- 등록 순서 (사용자가 함):
  1. https://partner.talk.naver.com/ 에서 내계정관리 > 새로운 톡톡 계정 만들기 (서비스 연결은 "나중에 하기"). 시험용이면 "개인"을 고르고, 프로필 이름 앞에 `[테스트]`를 붙이면 검색에 나오지 않는다. 검수가 끝나면 문자가 온다.
  2. 계정관리 > 개발자도구 > 챗봇 API 설정에서 약관에 동의하고 신청한다.
  3. 보내기 API에서 인증 값을 만들어 Render Environment의 `NAVERTALK_AUTH_KEY`에 넣는다. 비밀 문자열을 만들어 `NAVERTALK_WEBHOOK_SECRET`에 넣는다: `python -c "import secrets; print(secrets.token_urlsafe(24))"`.
  4. Webhook의 "이벤트 받을 URL"에 `{배포 주소}/api/navertalk/webhook/{비밀 문자열}`을 넣고, 이벤트에서 open과 send를 켠다.
- 알려진 한계: 서버가 잠들어 있으면 3초 안에 연결되지 않아 첫 글이 실패할 수 있다 (디스코드와 같다).

### 8-2. 카카오톡 (2026-11-21, `app/routers/kakao.py`, `tests/test_kakao.py`)
- 문서: [스킬 가이드](https://kakaobusiness.gitbook.io/main/tool/chatbot/skill_guide) (응답 형식, AI 챗봇 콜백, 스킬 만들기). 2026-11-21에 확인했다. 요금과 운영 승인 이야기는 문서에 없다. 사용자가 관리자센터에서 확인한다.
- 경로: `POST /api/kakao/skill`. 카카오는 요청 서명을 주지 않는다. 오픈빌더 스킬 설정의 "헤더값"에 `X-Spot-Secret: {KAKAO_SKILL_SECRET}`을 넣게 하고, 틀리면 403을 돌려준다 (`TODO(확인)`: 헤더값 입력 형식).
- 스킬은 **5초 안에** 답해야 한다. 블록에 **AI 챗봇 콜백**을 켜면 요청에 `userRequest.callbackUrl`이 온다. 그러면 `{"version":"2.0","useCallback":true,"data":{"text":"기다려 주세요"}}`로 바로 답하고, 뒤에서 처리한 뒤 callbackUrl로 응답을 **한 번** POST한다 (5분 안). callbackUrl이 없으면 바로 처리해서 답한다. 이때 AI 답변은 5초를 넘길 수 있다.
- 콜백은 봇 테스트 화면에서는 시험 토큰이라 거절될 수 있다. 배포한 채널에서 시험한다.
- 응답 제한: 말풍선 3개, 바로가기 버튼 10개, 캐러셀 카드 10장, 카드 버튼 3개, 버튼 이름 14자, simpleText 1000자, 캐러셀 안 textCard 설명 128자.
  - 정책 카드: textCard 캐러셀 하나로 묶는다. 제목은 정책 이름, 버튼은 [자세히 보기]와 [원문 보기] 링크다. "최종 확인" 문구는 카드 밖 글로 뺀다.
  - 고르는 버튼: 10개 이하면 바로가기 버튼으로 보낸다. 시·도(17개)와 시·군·구(최대 32개)는 카드 3개씩 캐러셀로 보내고(30개까지), 남는 것은 바로가기 버튼으로 보낸다.
  - 이어진 글 말풍선은 하나로 합친다.
- 버튼은 `action: "message"`, `messageText`=버튼 이름 전체, `extra.code`=누름 코드다. 누름은 `action.clientExtra.code`로 받는다. 그 값이 없으면, 그 사용자에게 마지막으로 보여 준 버튼 이름과 같은 말인지 보고 코드를 찾는다 (메모리 30분, 버튼 이름만 기억하고 대화 글은 기억하지 않는다). 그래서 시·군·구 이름을 직접 적어도 된다.
- 빈 말(웰컴 블록), "안내"는 인사로, "처음부터"는 조건 지우기로 처리한다.
- 등록 순서 (사용자가 함):
  1. 카카오톡 채널 관리자센터(https://center-pf.kakao.com)에서 채널을 만든다.
  2. 카카오 i 오픈빌더(https://chatbot.kakao.com)에서 봇을 만들고 채널을 연결한다 (개발 채널, 운영 채널).
  3. 스킬 탭에서 스킬을 만든다. URL에는 `{배포 주소}/api/kakao/skill`을 넣고, 헤더값에는 `X-Spot-Secret`과 비밀 문자열을 넣는다. 같은 비밀 문자열을 Render Environment의 `KAKAO_SKILL_SECRET`에 넣는다.
  4. **폴백 블록**과 **웰컴 블록**에 이 스킬을 연결한다. 응답은 "스킬데이터로 사용"으로 하고, 블록 더보기(…) > Callback 설정을 켠다.
  5. 배포한다 (최대 30분). 채널에서 직접 시험한다.
- `TODO(확인)`: 폴백 블록에 스킬을 연결할 수 있는지는 문서에 적혀 있지 않다. 안 되면 모든 말을 받는 블록을 따로 만든다.

## 9. 참고 문서

- `PROJECT_SPEC.md` (전체 요구사항), `README.md` (실행 방법, 평가 결과)
- PRD 문서: https://claude.ai/artifact/CPZcufwjNUgdmfiBKoGmWT
- 텔레그램 Bot API: https://core.telegram.org/bots/api (setWebhook, sendMessage, InlineKeyboardMarkup, answerCallbackQuery)
- 디스코드 Interactions: https://discord.com/developers/docs/interactions/receiving-and-responding (서명 검사, 응답 종류, 3초 제한, 후속 메시지)
