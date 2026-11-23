"""채팅 처리 핵심: 질문 분석 → 되묻기 → 검색 → 답변 생성.

웹 채팅과 메신저(텔레그램·디스코드·네이버 톡톡·카카오톡)가 함께 쓴다. HTTP와 상관없는 순수 로직만 둔다.
서버는 대화를 저장하지 않는다. 이전 대화와 정해진 조건은 부르는 쪽이 매번 같이 보낸다.
"""
from app.services import analyzer, answerer, faq, followup, llm, privacy, rate_limit, retriever

MESSAGE_LIMIT = 300
HISTORY_LIMIT = 6
HISTORY_TEXT_LIMIT = 300

# 되묻기 문구는 LLM이 만들지 않고 여기 정해 둔 것만 쓴다.
ASK_TEXT = {
    ("age_group", "region"): "맞는 지원을 찾으려고 몇 가지만 여쭤볼게요. 나이대와 사시는 지역을 골라 주세요.",
    ("age_group",): "맞는 지원을 찾으려고 한 가지만 여쭤볼게요. 나이대를 골라 주세요.",
    ("region",): "맞는 지원을 찾으려고 한 가지만 여쭤볼게요. 사시는 지역을 골라 주세요.",
}
NONE_TEXT = (
    "말씀하신 상황에 맞는 지원을 찾지 못했어요. "
    "가까운 주민센터나 보건복지상담센터(국번 없이 129)에 물어보시면 도움을 받을 수 있어요."
)
REGION_HINT = "사시는 지역을 알려 주시면 지역 지원도 찾아 드려요."
FALLBACK_TEXT = "지금은 AI 답변이 어려워요. 버튼으로 찾아 볼까요?"
USER_LIMIT_TEXT = "오늘 질문 횟수를 다 쓰셨어요. 버튼으로 찾기는 계속 쓸 수 있어요."


def merge_conditions(sent, analysis):
    """브라우저가 보낸 조건과 이번 분석 결과를 합친다. 버튼으로 고른 값이 우선."""
    merged = {
        key: sent.get(key) or analysis.get(key)
        for key in ("age_group", "gender", "region_code", "household")
    }
    # "75살이고 서울 살아요"처럼 조건만 덧붙인 말이면 앞에서 정한 분야·검색 문장을 그대로 둔다.
    # 앞 질문을 이어 쓰는 것은 아래를 모두 만족할 때만이다. 하나라도 아니면 새 질문으로 본다.
    #  - 분야가 "기타"이고, 찾아볼 제도 이름도 없다 ("영화 보러 가는데 지원금" → 문화누리카드는 새 질문)
    #  - 나이·지역·성별·가구 형태 중 하나라도 말했다 (조건을 말하지 않은 글은 조건만 덧붙인 말이 아니다)
    told_condition = any(analysis.get(k) for k in ("age_group", "gender", "region_code", "region_text", "household"))
    keep_previous = (bool(sent.get("search_text")) and analysis.get("need") == "기타"
                     and not analysis.get("has_terms") and told_condition)
    source = sent if keep_previous else analysis
    merged["for_child"] = bool(source.get("for_child"))
    merged["need"] = source.get("need")
    merged["search_text"] = source.get("search_text")
    return merged


def fallback(text, conditions=None):
    """AI 답변이 안 될 때: 화면은 버튼 조회로 안내한다. 조건은 버튼 조회에 이어 쓰라고 돌려준다."""
    response = {"type": "fallback", "text": text}
    if conditions:
        response["conditions"] = conditions
    return response


def _over_limit(client_key, is_question, conditions):
    """하루 한도를 넘었으면 fallback 응답, 아니면 None (횟수를 1 올린다)."""
    limit = rate_limit.check(client_key, is_question=is_question)
    if limit == rate_limit.OK:
        return None
    text = USER_LIMIT_TEXT if limit == rate_limit.USER_LIMIT else FALLBACK_TEXT
    return fallback(text, {k: conditions.get(k) for k in ("age_group", "gender", "region_code", "household")})


def error(text):
    """잘못된 질문(빈 글, 너무 긴 글). 웹은 400 오류로, 메신저는 안내 글로 바꿔 보여 준다."""
    return {"type": "error", "text": text}


def handle(req, client_key):
    """ChatRequest를 받아 ask / result / info / none / fallback / error 중 하나를 돌려준다.

    웹(/api/chat)과 메신저가 함께 쓴다. 대화 글은 저장하지 않는다.
    """
    message = req.message.strip()
    if len(message) > MESSAGE_LIMIT:
        return error("조금만 짧게 말씀해 주세요.")
    sent = req.conditions.model_dump()
    if not message and not sent.get("search_text"):
        return error("궁금한 점을 말씀해 주세요.")

    masked = False
    topic = None
    if message:
        message, masked = privacy.mask(message)
        # 보여 드린 정책을 이어서 묻는 질문("서류는 뭐가 필요해요?")이면 AI 없이 DB 값으로 답한다.
        info = followup.answer(message, req.shown) if req.shown else None
        if info:
            limited = _over_limit(client_key, False, sent)   # AI를 안 쓰므로 재호출처럼 센다
            if limited:
                return limited
            notice = " " + privacy.NOTICE if masked else ""
            return {**info, "text": info["text"] + notice, "conditions": sent}
        topic = faq.match(message)   # 자주 묻는 질문이면 AI 없이 답한다
    # AI를 쓰지 않는 자주 묻는 질문은 전체 한도(Groq 보호용)를 덜 쓰도록 재호출처럼 센다.
    faq_question = bool(message) and bool(topic)
    limited = _over_limit(client_key, bool(message) and not topic, sent)
    if limited:
        return limited

    if topic:
        # 나이·지역은 버튼으로 고른 값이 먼저, 없으면 글에서 낱말로 찾는다 ("75살", "서울 강남구").
        rules = analyzer.analyze_by_rules(message)
        conditions = {k: sent.get(k) for k in ("gender", "household")}
        conditions.update(
            age_group=sent.get("age_group") or rules["age_group"],
            region_code=sent.get("region_code") or rules["region_code"],
            for_child=faq.for_child(topic, message), need=topic["need"],
            search_text=topic["search_text"], faq=topic["id"],
        )
    elif message:
        history = [
            {"role": h.role, "text": privacy.mask(h.text[:HISTORY_TEXT_LIMIT])[0]}
            for h in req.history[-HISTORY_LIMIT:]
        ]
        conditions = {**merge_conditions(sent, analyzer.analyze(message, history)), "faq": None}
    else:
        # 버튼으로 조건만 고른 호출: 분석(LLM)을 건너뛰고 바로 검색한다.
        conditions = sent
    notice = " " + privacy.NOTICE if masked else ""

    missing = tuple(
        name for name, key in (("age_group", "age_group"), ("region", "region_code"))
        if not conditions.get(key)
    )
    if missing and not req.asked:
        return {"type": "ask", "text": ASK_TEXT[missing] + notice, "ask": list(missing), "conditions": conditions}

    topic = faq.BY_ID.get(conditions.get("faq") or "")
    if topic:
        cards = faq.policies(topic, conditions, message)
        if cards:   # 맞는 정책이 없으면 아래의 의미 검색 + AI 답변으로 넘어간다
            text = faq.result_text(topic)
            if not conditions["region_code"]:
                text += " " + REGION_HINT
            return {"type": "result", "text": text + notice, "policies": cards, "conditions": conditions,
                    "via": "faq"}
        if faq_question:
            # 처음에는 AI를 안 쓸 줄 알고 재호출로 셌지만, 이제 답변 AI를 쓰므로 질문 1번으로 다시 센다.
            limited = _over_limit(client_key, True, conditions)
            if limited:
                return limited

    age_group, for_child = conditions["age_group"], bool(conditions.get("for_child"))
    candidates = retriever.search_semantic(
        analyzer.expand(conditions["search_text"]),
        age_group=age_group,
        gender=conditions["gender"],
        region_code=conditions["region_code"],
        household=conditions["household"],
        for_child=for_child,
        # DB의 나이 칸은 느슨하므로 이름·지원 대상 글의 나이 무리(아동·청년·노인·임산부)로 한 번 더 거른다.
        # 답변 AI가 판단할 몫이 줄고, 빠진 자리는 나이가 맞는 후보로 채운다.
        keep=lambda row: faq.fits_age(row, age_group, for_child, " ".join([message, conditions["search_text"] or ""])),
    )
    if not candidates:
        return {"type": "none", "text": NONE_TEXT + notice, "conditions": conditions}

    try:
        answer = answerer.answer(conditions["search_text"], conditions, candidates)
    except llm.LLMError:
        return fallback(FALLBACK_TEXT, conditions)
    if not answer["picks"]:
        # 아주 가까운 후보가 있는데 AI가 하나도 고르지 않으면, 그 후보들을 그대로 보여 준다.
        # 같은 질문에도 AI가 가끔 빈 picks 를 내서 "찾지 못했어요"가 나왔다 (2026-11-19, 11-21 영화 질문).
        # 한 번 더 묻던 방식은 두 번 다 비기도 하고 토큰을 두 배로 써서 바꿨다. 카드 내용은 모두 DB 값이다.
        # 질문에 그 대상 이야기가 없는 특정 대상 전용 정책(장애인, 국가유공자 등)은 AI 판단 없이 보여 주지 않는다.
        context = " ".join([message, conditions["search_text"] or ""])
        answer = answerer.close_picks([c for c in candidates
                                       if not faq.is_special(c["name"], context, c.get("tag_special"))])
    if not answer["picks"]:
        return {"type": "none", "text": NONE_TEXT + notice, "conditions": conditions}

    # 카드 내용은 DB 값 그대로. LLM이 쓴 것은 한 줄 요약(one_line)뿐이다.
    by_id = {c["id"]: c for c in candidates}
    policies = [
        {**retriever.to_card(by_id[p["id"]]), "one_line": p["one_line"]} for p in answer["picks"]
    ]
    text = answer["text"]
    if not conditions["region_code"]:
        text += " " + REGION_HINT
    return {"type": "result", "text": text + notice, "policies": policies, "conditions": conditions}
