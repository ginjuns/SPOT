// 정책 상세: 지원 대상, 지원 내용, 신청 방법, 문의처(전화 걸기), 원문 링크, 자료 기준일
(function () {
  "use strict";
  const { api, el, safeUrl, showLoading, showError } = window.SPOT;

  const main = document.getElementById("main");
  const LONG_TEXT = 400;   // 이보다 길면 접어 두고 [더 보기]를 둔다

  document.getElementById("back").addEventListener("click", () => {
    // 이 사이트 안에서 넘어왔으면 그 화면으로, 링크로 바로 열었으면 처음 화면으로
    if (history.length > 1 && document.referrer.startsWith(location.origin)) history.back();
    else location.href = "index.html";
  });

  // 빈 줄이 여러 개 이어진 원문을 읽기 좋게 줄인다
  function tidy(text) {
    return (text || "").replace(/[ \t]+\n/g, "\n").replace(/\n{2,}/g, "\n").trim();
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
    if (policy.has_income_rule) {
      head.append(el("span", "badge", "소득 기준 있음"));
      head.append(el("p", "muted", "소득이나 재산에 따라 받을 수 있는지가 달라져요. 신청하는 곳에서 확인해 주세요."));
    }
    if (policy.summary) head.append(el("p", "", tidy(policy.summary)));

    const parts = [
      head,
      section("지원 대상", policy.target),
      section("지원 내용", policy.content),
      section("선정 기준", policy.criteria),
      section("신청 방법", policy.how_to_apply),
      section("신청하는 곳", policy.apply_place),
      contactSection(policy.contact),
    ].filter(Boolean);

    const foot = el("section", "section stack");
    const url = safeUrl(policy.url);
    if (url) {
      const origin = el("a", "btn btn-primary", "원문 보기 (정부24)");
      origin.href = url;
      origin.target = "_blank";
      origin.rel = "noopener";
      foot.append(origin);
    }
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
    } catch (e) {
      stop();
      showError(main, e.message, start);
    }
  }

  start();
})();
