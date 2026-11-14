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
  contact          TEXT,                  -- 문의처
  url              TEXT,                  -- 원문 링크
  region_code      TEXT,                  -- 시·도(2자리) 또는 시·군·구(5자리), 전국은 NULL, 지역 불명은 'UNKNOWN'
  age_min          INT,                   -- NULL = 제한 없음
  age_max          INT,
  gender           CHAR(1),               -- 'M', 'F', NULL(무관)
  household        TEXT[],                -- options.json의 value 그대로. 예: {'single','single_parent'}; NULL = 무관
  has_income_rule  BOOLEAN DEFAULT FALSE, -- 소득·재산 기준이 있는 정책
  embedding        vector(384),           -- multilingual-e5-small
  collected_at     DATE NOT NULL          -- 데이터 기준일
);

CREATE INDEX IF NOT EXISTS idx_policy_region ON policy (region_code);
-- 벡터 인덱스(HNSW)는 만들지 않는다. 이유는 PROJECT_SPEC.md 6장 참고.

CREATE TABLE IF NOT EXISTS region (
  code     TEXT PRIMARY KEY,   -- 시·군·구 코드 5자리 (시·도는 2자리)
  sido     TEXT NOT NULL,
  sigungu  TEXT                -- 시·도 행은 NULL
);
