"""시·도, 시·군·구 목록 만들기와 DB 입력.

  python scripts/load_regions.py --build   # data/raw/serviceList.json 의 기관명으로 data/regions.csv 갱신
  python scripts/load_regions.py           # data/regions.csv 를 DB의 region 테이블에 넣기

지역 코드는 법정동 코드가 아니라 이 프로젝트에서 붙인 번호다.
  시·도 2자리, 시·군·구 5자리(앞 2자리 = 시·도).
한번 붙인 코드는 공유 링크에 쓰이므로 --build 를 다시 해도 바꾸지 않고, 새 지역만 뒤에 추가한다.
"""
import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402

CSV_PATH = config.DATA_DIR / "regions.csv"
RAW_LIST = config.DATA_DIR / "raw" / "serviceList.json"


def read_csv():
    if not CSV_PATH.exists():
        return []
    with open(CSV_PATH, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def build():
    rows = read_csv()
    sido_code = {r["sido"]: r["code"] for r in rows if not r["sigungu"]}
    sigungu_code = {(r["sido"], r["sigungu"]): r["code"] for r in rows if r["sigungu"]}

    services = json.loads(RAW_LIST.read_text(encoding="utf-8"))["data"]
    sidos, sigungus = set(), set()
    for s in services:
        name = (s.get("소관기관명") or "").strip()
        if s.get("소관기관유형") == "광역시도":
            sidos.add(name)
        elif s.get("소관기관유형") == "시군구":
            sido, _, rest = name.partition(" ")
            if rest:
                sidos.add(sido)
                sigungus.add((sido, rest))
            else:
                print("시·도 이름이 없는 시·군·구 기관명 (건너뜀):", name)

    added = 0
    for sido in sorted(sidos - sido_code.keys()):
        used = {int(c) for c in sido_code.values()}
        sido_code[sido] = str(max(used | {10}) + 1)
        added += 1
    for sido, name in sorted(sigungus - sigungu_code.keys()):
        prefix = sido_code[sido]
        used = {int(c[2:]) for c in sigungu_code.values() if c.startswith(prefix)}
        sigungu_code[(sido, name)] = prefix + str(max(used | {100}) + 1)
        added += 1

    out = [{"code": c, "sido": s, "sigungu": ""} for s, c in sido_code.items()]
    out += [{"code": c, "sido": s, "sigungu": g} for (s, g), c in sigungu_code.items()]
    out.sort(key=lambda r: r["code"])
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["code", "sido", "sigungu"])
        w.writeheader()
        w.writerows(out)
    print(f"regions.csv 저장: 시·도 {len(sido_code)}곳, 시·군·구 {len(sigungu_code)}곳 (새로 추가 {added}곳)")


def load():
    import psycopg

    rows = read_csv()
    if not rows:
        sys.exit("data/regions.csv 가 없습니다. 먼저 --build 를 실행하세요.")
    with psycopg.connect(config.DATABASE_URL) as conn:
        conn.cursor().executemany(
            "INSERT INTO region (code, sido, sigungu) VALUES (%s, %s, %s) "
            "ON CONFLICT (code) DO UPDATE SET sido = EXCLUDED.sido, sigungu = EXCLUDED.sigungu",
            [(r["code"], r["sido"], r["sigungu"] or None) for r in rows],
        )
        total = conn.execute("SELECT count(*) FROM region").fetchone()[0]
    print(f"region 테이블에 {len(rows)}행 저장 (현재 {total}행)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true", help="원본 기관명으로 regions.csv 갱신")
    args = parser.parse_args()
    if args.build:
        build()
    else:
        load()
