// 정책 상세: 지원 대상, 지원 내용, 신청 기간, 신청 방법, 준비할 서류, 문의처(전화 걸기), 원문 링크, 공유, 자료 기준일
(function () {
  "use strict";
  const { api, el, safeUrl, showLoading, showError, resultActions, speakButton, realText } = window.SPOT;
  const SPEAK_PART = 200;   // 읽어 줄 때 항목마다 앞부분만 읽는다 (너무 길면 듣기 힘들다)

  // [소리로 듣기]로 읽을 글: 이름, 요약, 지원 대상, 지원 내용, 신청 기간, 신청하는 곳
  function speechText(policy) {
    const parts = [
      [policy.name, ""],
      [policy.summary, ""],
      [policy.target, "지원 대상. "],
      [policy.content, "지원 내용. "],
      [policy.apply_period, "신청 기간. "],
      [policy.apply_place, "신청하는 곳. "],
    ];
    return parts
      .filter(([text]) => tidy(text))
      .map(([text, label]) => {
        const body = tidy(text).replace(/\n/g, " ");
        return label + (body.length > SPEAK_PART ? body.slice(0, SPEAK_PART) + " 등" : body) + ".";
      })
      .join(" ") + " 자세한 내용은 화면에서 확인해 주세요.";
  }

  const main = document.getElementById("main");
  const LONG_TEXT = 400;   // 이보다 길면 접어 두고 [더 보기]를 둔다
  // 소득 기준이 있는 정책에서 여는 복지로 "복지서비스 모의계산" 화면
  // TODO(확인): 2026-11-18에 주소가 열리는 것만 확인했다. 복지로 화면이 바뀌면 주소를 고친다.
  const BOKJIRO_MOCK_URL = "https://www.bokjiro.go.kr/ssis-tbu/twatbz/mkclAsis/mkclInsertNblgPage.do";

  // 빈 줄이 여러 개 이어진 원문을 읽기 좋게 줄인다. "상동"처럼 내용이 없는 값은 빈 글로 (항목을 숨긴다)
  function tidy(text) {
    return realText((text || "").replace(/[ \t]+\n/g, "\n").replace(/\n{2,}/g, "\n"));
  }

  function section(title, text) {
    const body = tidy(text);
    if (!body) return null;
    const box = el("section", "card section");
    box.append(el("h2", "", title));
    const p = el("p", "body", body);
    box.append(p);
    if (body.length > LONG_TEXT) {
      p.classList.add("clamped");
      const more = el("button", "btn btn-quiet", "더 보기");
      more.type = "button";
      more.addEventListener("click", () => {
        const folded = p.classList.toggle("clamped");
        more.textContent = folded ? "더 보기" : "접기";
      });
      box.append(more);
    }
    return box;
  }

  // 문의처는 "기관이름/전화번호||기관이름/전화번호" 꼴로 들어 있다
  function contactSection(contact) {
    const entries = tidy(contact).split("||").map((s) => s.trim()).filter(Boolean);
    if (entries.length === 0) return null;
    const box = el("section", "card section");
    box.append(el("h2", "", "문의처"));
    const list = el("ul", "contact-list");
    entries.forEach((entry) => {
      const item = el("li");
      const cut = entry.lastIndexOf("/");
      const who = cut > 0 ? entry.slice(0, cut).trim() : "";
      const phone = (cut >= 0 ? entry.slice(cut + 1) : entry).trim();
      const digits = phone.replace(/[^0-9]/g, "");
      // 전화번호처럼 보일 때만 전화 걸기 버튼으로 만든다
      if (/^[0-9][0-9\-\s~()]*$/.test(phone) && digits.length >= 3 && digits.length <= 12) {
        if (who) item.append(el("span", "who", who));
        const call = el("a", "btn", "전화 걸기 " + phone);
        call.href = "tel:" + digits;
        item.append(call);
      } else {
        item.append(el("span", "who", entry));
      }
      list.append(item);
    });
    box.append(list);
    return box;
  }

  function render(policy) {
    document.title = policy.name + " - SPOT";
    const head = el("section", "card");
    head.append(el("h1", "", policy.name));
    head.append(el("p", "agency muted", policy.agency || ""));
    if (policy.source) {
      head.append(el("span", "badge badge-private", policy.source));
      head.append(el("p", "muted", "나라에서 하는 지원이 아니라 " + (policy.agency || "민간 단체") +
        "에서 하는 지원이에요. 모집 때와 조건은 기관에 꼭 확인해 주세요."));
    }
    if (policy.has_income_rule) {
      head.append(el("span", "badge", "소득 기준 있음"));
      head.append(el("p", "muted", "소득이나 재산에 따라 받을 수 있는지가 달라져요. 복지로 모의계산으로 미리 알아보거나, 주민센터에 물어보세요."));
      const mock = el("a", "btn", "복지로에서 모의계산 해 보기");
      mock.href = BOKJIRO_MOCK_URL;
      mock.target = "_blank";
      mock.rel = "noopener";
      head.append(mock);
    }
    if (policy.summary) head.append(el("p", "", tidy(policy.summary)));
    const speak = speakButton(() => speechText(policy));
    if (speak) head.append(speak);

    const parts = [
      head,
      section("지원 대상", policy.target),
      section("지원 내용", policy.content),
      section("선정 기준", policy.criteria),
      section("신청 기간", policy.apply_period),
      section("신청 방법", policy.how_to_apply),
      section("준비할 서류", policy.documents),
      section("신청하는 곳", policy.apply_place),
      contactSection(policy.contact),
    ].filter(Boolean);

    const foot = el("section", "section stack");
    const url = safeUrl(policy.url);
    if (url) {
      // 정부24에 없는 지자체 복지는 복지로 화면으로 간다
      const origin = el("a", "btn btn-primary", policy.source ? "기관 홈페이지 보기"
        : url.includes("bokjiro.go.kr") ? "원문 보기 (복지로)" : "원문 보기 (정부24)");
      origin.href = url;
      origin.target = "_blank";
      origin.rel = "noopener";
      foot.append(origin);
    }
    // 이 지원 하나를 가족에게 보내거나, 주민센터 창구에서 큰 글씨로 보여 준다
    foot.append(resultActions(null, [policy.id]));
    foot.append(el("p", "muted", "자료 기준일 " + policy.collected_at + " · 그 뒤에 내용이 바뀌었을 수 있어요."));
    parts.push(foot);

    main.replaceChildren(...parts);
  }

  async function start() {
    const id = new URLSearchParams(location.search).get("id");
    if (!id) {
      showError(main, "정책을 찾지 못했어요. 주소를 다시 확인해 주세요.");
      return;
    }
    const stop = showLoading(main);
    try {
      const policy = await api.get("/api/policy/" + encodeURIComponent(id));
      stop();
      render(policy);
      // 이번 달 많이 본 지원 순위에 센다. 실패해도 화면에는 상관없다.
      api.post("/api/policy/" + encodeURIComponent(id) + "/view", {}).catch(() => {});
    } catch (e) {
      stop();
      showError(main, e.message, start);
    }
  }

  start();
})();
