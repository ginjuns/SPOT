"""보여 드린 정책을 이어서 묻는 질문에 AI 없이 DB 값으로 답하기.

결과 카드를 본 뒤 "서류는 뭐가 필요해요?", "어디서 신청해요?"라고 물으면, 전에는 처음부터 다시 검색했다.
이제 부르는 쪽(브라우저·메신저)이 방금 보여 준 카드의 정책 ID만 같이 보내면(shown), 그 정책의
준비할 서류·신청 방법·신청 기간·문의처를 DB 값 그대로 보여 준다. 대화 글이 아니라 ID만 오가고 저장하지 않는다.

이어서 묻는 질문으로 보는 것은 묻는 말("서류", "어디서 신청" 등)이 있고, 아래 중 하나일 때다.
  - 보여 준 정책의 이름이 나온다 ("기초연금 서류")
  - 몇 번째 정책인지 말한다 ("2번", "첫 번째")
  - 앞의 것을 가리키는 말이 있다 ("그거", "이 지원")
  - 다른 내용이 없는 짧은 글이다 ("서류는 뭐가 필요해요?")
"장애인 콜택시는 어디서 신청해요?"처럼 다른 것을 묻는 긴 글, "근로장려금 언제 신청해요"처럼 자주 묻는 질문
주제 낱말이 있는 글은 지금처럼 새 질문으로 찾는다.
"""
import re

from app import db
from app.services import faq

MAX_POLICIES = 3      # 한 번에 보여 줄 정책 수 (글이 너무 길어지지 않게)
VALUE_LIMIT = 200     # 항목마다 보여 줄 글자 수
SHORT_LIMIT = 12      # 띄어쓰기를 뺀 글자 수가 이 이하면 다른 내용이 없는 짧은 글로 본다

# 묻는 것 → (DB 열, 이름) 목록과 그것을 묻는 말
ASKS = [
    ("documents", [("documents", "준비할 서류")],
     ["서류", "준비물", "챙겨", "챙길", "구비", "가져가", "가지고가"]),
    ("apply", [("how_to_apply", "신청 방법"), ("apply_place", "신청하는 곳")],
     ["어디서", "어디에", "어디로", "어떻게신청", "신청방법", "신청하려면", "신청은", "신청할", "접수"]),
    ("period", [("apply_period", "신청 기간")],
     ["언제까지", "신청기간", "언제신청", "언제부터", "마감", "기한"]),
    ("contact", [("contact", "문의처")],
     # "전화"만 보면 "전화요금 지원 있나요"(통신요금 감면)가 걸려서 더 긴 말만 쓴다
     ["전화번호", "전화는", "전화해", "전화할", "문의처", "문의는", "문의하", "연락처", "물어볼", "어디에물어"]),
]
POINTING = ["그거", "그것", "이거", "이것", "저거", "그지원", "이지원", "위에", "방금", "아까", "거기"]
ORDINALS = {"첫번째": 0, "첫째": 0, "두번째": 1, "둘째": 1, "세번째": 2, "셋째": 2, "네번째": 3, "다섯번째": 4}
GENERIC_PARTS = {"지원", "지원사업", "서비스", "사업", "지급", "제도"}
EMPTY_VALUE = "자료에 적혀 있지 않아요. 문의처에 물어봐 주세요."
FINAL_CHECK = "자격은 신청하는 곳에서 최종 확인해 주세요."


def _squash(text):
    return "".join((text or "").split()).lower()


def asked_fields(message):
    """글에서 묻는 것 목록 (ASKS 의 이름). 없으면 빈 목록."""
    t = _squash(message)
    return [kind for kind, _, words in ASKS if any(w in t for w in words)]


def _name_parts(name):
    """정책 이름에서 그 정책을 가리킬 만한 조각 ("노인일자리 및 사회활동 지원" → 노인일자리, 사회활동)."""
    parts = [p.lower() for p in re.split(r"[\s()·,ㆍ/]+", name or "")]
    return [p for p in parts if len(p) >= 3 and p not in GENERIC_PARTS] or [_squash(name)]


def pick_policies(message, rows, other_topic=False):
    """보여 준 정책(rows, 카드 순서) 중 글이 가리키는 것. 가리키는 것이 분명하지 않으면 None.

    other_topic: 글에 자주 묻는 질문 주제 낱말이 있다 ("근로장려금 언제 신청해요"). 이때는 짧은 글이어도
    다른 것을 묻는 새 질문으로 보고, 이름이나 번호로 보여 준 정책을 가리킬 때만 이어서 묻는 질문으로 본다.
    """
    t = _squash(message)
    named = [r for r in rows if any(p in t for p in _name_parts(r["name"]))]
    if named:
        return named
    number = re.search(r"(\d)\s*번", message)
    if number and 1 <= int(number.group(1)) <= len(rows):
        return [rows[int(number.group(1)) - 1]]
    for word, index in ORDINALS.items():
        if word in t and index < len(rows):
            return [rows[index]]
    if not other_topic and (any(w in t for w in POINTING) or len(t) <= SHORT_LIMIT):
        return rows
    return None


def _value(text):
    """DB 글을 보여 줄 모양으로: 빈 줄을 빼고 앞 VALUE_LIMIT 자까지. 문의처의 '||'는 쉼표로."""
    text = (text or "").replace("||", ", ").strip()
    if not text:
        return EMPTY_VALUE
    lines = [" ".join(line.split()) for line in text.splitlines()]
    text = "\n".join(line for line in lines if line)
    return text if len(text) <= VALUE_LIMIT else text[:VALUE_LIMIT].rstrip() + "…"


def answer(message, shown_ids):
    """이어서 묻는 질문이면 {"type": "info", ...} 응답, 아니면 None (부르는 쪽이 새 질문으로 찾는다)."""
    kinds = asked_fields(message)
    if not kinds or not shown_ids:
        return None
    rows = db.query(
        "SELECT id, name, how_to_apply, apply_place, apply_period, documents, contact "
        "FROM policy WHERE id = ANY(%(ids)s)", {"ids": list(shown_ids)},
    )
    order = {pid: i for i, pid in enumerate(shown_ids)}
    rows.sort(key=lambda r: order[r["id"]])
    picked = pick_policies(message, rows, other_topic=bool(faq.matched_topics(message))) if rows else None
    if not picked:
        return None
    columns = [col for kind, cols, _ in ASKS if kind in kinds for col in cols]
    blocks = []
    for r in picked[:MAX_POLICIES]:
        lines = [f"■ {r['name']}"] + [f"{label}: {_value(r[col])}" for col, label in columns]
        blocks.append("\n".join(lines))
    text = "\n\n".join(blocks)
    if len(picked) > MAX_POLICIES:
        text += "\n\n나머지 지원은 [자세히 보기]에서 보실 수 있어요."
    text += "\n\n" + FINAL_CHECK
    return {"type": "info", "text": text,
            "policies": [{"id": r["id"], "name": r["name"]} for r in picked[:MAX_POLICIES]]}
