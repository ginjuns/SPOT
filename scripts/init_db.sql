-- SPOT 테이블 생성 SQL
-- Neon 콘솔의 SQL Editor에 붙여 넣어 실행한다. 여러 번 실행해도 안전하다.
-- 사용자 대화와 관련된 테이블은 만들지 않는다.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS policy (
  id               TEXT PRIMARY KEY,      -- 서비스 ID
  name             TEXT NOT NULL,         -- 정책명
  agency           TEXT,                  -- 소관 기관
  category         TEXT,                  -- 서비스 분야 (API 제공값)
  summary          TEXT,                  -- 서비스 목적 요약
  target           TEXT,                  -- 지원 대상
  criteria         TEXT,                  -- 선정 기준
  content          TEXT,                  -- 지원 내용
  how_to_apply     TEXT,                  -- 신청 방법
  apply_place      TEXT,                  -- 접수 기관
  apply_period     TEXT,                  -- 신청 기한 ("상시신청", "매년 1월", 날짜 등 원문 그대로)
  documents        TEXT,                  -- 준비할 서류 (없으면 NULL)
  contact          TEXT,                  -- 문의처
  url              TEXT,                  -- 원문 링크
  region_code      TEXT,                  -- 시·도(2자리) 또는 시·군·구(5자리), 전국은 NULL, 지역 불명은 'UNKNOWN'
  age_min          INT,                   -- NULL = 제한 없음
  age_max          INT,
  gender           CHAR(1),               -- 'M', 'F', NULL(무관)
  household        TEXT[],                -- options.json의 value 그대로. 예: {'single','single_parent'}; NULL = 무관
  has_income_rule  BOOLEAN DEFAULT FALSE, -- 소득·재산 기준이 있는 정책
  for_person       BOOLEAN NOT NULL DEFAULT TRUE, -- 개인·가구가 받는 지원 (FALSE = 소상공인·법인·시설·단체만)
  views            INT NOT NULL DEFAULT 0, -- 정부24 조회수 (많이 찾는 정책을 먼저 보여 준다)
  embedding        vector(384),           -- multilingual-e5-small
  collected_at     DATE NOT NULL          -- 데이터 기준일
);

-- 예전에 만든 테이블에는 아래 열들이 없으므로 더해 준다.
-- 그 뒤에 `python scripts/ingest.py --from-raw --no-embed` 를 돌리면 값이 채워진다.
ALTER TABLE policy ADD COLUMN IF NOT EXISTS for_person BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE policy ADD COLUMN IF NOT EXISTS views INT NOT NULL DEFAULT 0;
ALTER TABLE policy ADD COLUMN IF NOT EXISTS apply_period TEXT;
ALTER TABLE policy ADD COLUMN IF NOT EXISTS documents TEXT;
-- 정책 검색용 꼬리표 (data/policy_tags.tsv, 2026-11-23). 검색에만 쓰고 화면에는 보이지 않는다.
ALTER TABLE policy ADD COLUMN IF NOT EXISTS tag_ages TEXT[];     -- 받는 사람 나이 무리: child, youth, middle, elder, pregnant, parent, all
ALTER TABLE policy ADD COLUMN IF NOT EXISTS tag_special TEXT[];  -- 특정 대상 전용: disabled, veteran, defector, multicultural, farmer, injured_worker
ALTER TABLE policy ADD COLUMN IF NOT EXISTS tag_words TEXT;      -- 어르신이 평소에 할 법한 말 (의미 검색 글에 붙인다)

CREATE INDEX IF NOT EXISTS idx_policy_region ON policy (region_code);
-- 벡터 인덱스(HNSW)는 만들지 않는다. 이유는 PROJECT_SPEC.md 6장 참고.

-- 정책 상세 화면 조회수 (한 달 단위 순위용, 2026-11-25). 누가 봤는지는 저장하지 않고 정책별 숫자만 남긴다.
CREATE TABLE IF NOT EXISTS policy_view_month (
  period_start DATE NOT NULL,   -- 이 달 순위가 시작한 날 (RANKING_START 부터 한 달씩)
  policy_id    TEXT NOT NULL,
  views        INT  NOT NULL DEFAULT 0,
  PRIMARY KEY (period_start, policy_id)
);

CREATE TABLE IF NOT EXISTS region (
  code     TEXT PRIMARY KEY,   -- 시·군·구 코드 5자리 (시·도는 2자리)
  sido     TEXT NOT NULL,
  sigungu  TEXT                -- 시·도 행은 NULL
);
