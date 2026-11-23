// 서버 호출과 화면 공통 함수. 모든 화면에서 먼저 불러온다.
(function () {
  "use strict";

  async function request(path, options) {
    let response;
    try {
      response = await fetch(path, options);
    } catch (e) {
      throw new Error("인터넷 연결을 확인하고 다시 해 주세요.");
    }
    let data = null;
    try {
      data = await response.json();
    } catch (e) {
      // 서버가 깨어나는 중이면 JSON이 아닌 응답이 올 수 있다
    }
    if (!response.ok || data === null) {
      throw new Error((data && data.error) || "잠시 문제가 생겼어요. 조금 뒤에 다시 해 주세요.");
    }
    return data;
  }

  const api = {
    get: (path) => request(path),
    post: (path, body) =>
      request(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
  };

  // 글자는 항상 textContent 로 넣는다 (DB 글이 HTML로 해석되지 않게).
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function button(label, onClick, className) {
    const node = el("button", className || "btn", label);
    node.type = "button";
    node.addEventListener("click", onClick);
    return node;
  }

  function safeUrl(url) {
    return typeof url === "string" && /^https?:\/\//.test(url) ? url : null;
  }

  // "찾고 있어요…" 표시. 무료 서버가 잠들어 있으면 오래 걸리므로 5초 뒤에 안내를 덧붙인다.
  function showLoading(box) {
    box.replaceChildren(el("p", "status", "찾고 있어요…"));
    const timer = setTimeout(() => {
      if (box.isConnected && box.querySelector(".status")) {
        box.append(el("p", "muted", "처음 여실 때는 1분쯤 걸릴 수 있어요. 조금만 기다려 주세요."));
      }
    }, 5000);
    return () => clearTimeout(timer);
  }

  function showError(box, message, onRetry) {
    box.replaceChildren(el("p", "status", message));
    if (onRetry) box.append(button("다시 해 보기", onRetry, "btn btn-primary"));
  }

  // 원문에 내용 대신 들어 있는 말("상동" = 위와 같음, "-", "해당없음" 등)은 보여 주지 않는다
  const EMPTY_WORDS = /^(상동|상동함|위와 같음|-+|없음|해당없음|해당 없음|\.)$/;
  function realText(text) {
    const value = (text || "").trim();
    return EMPTY_WORDS.test(value) ? "" : value;
  }

  // 정책 카드. 내용은 서버가 준 DB 값을 그대로 보여 준다.
  function policyCard(policy) {
    const card = el("article", "card");
    card.append(el("h2", "", policy.name));
    card.append(el("p", "agency", policy.agency || ""));
    if (policy.has_income_rule) card.append(el("span", "badge", "소득 기준 있음"));
    const oneLine = realText(policy.one_line);
    if (oneLine) card.append(el("p", "", oneLine));
    // 신청 기간이 정해져 있으면 카드에서 바로 보여 준다 (늘 신청할 수 있는 것, 긴 설명은 상세 화면에서)
    // 적힌 연도가 모두 지난해 이전이면("2022.10.16 ~ 2022.11.22") 카드에는 보여 주지 않는다.
    // 원본 자료에 옛 기간이 그대로 남은 정책이 있다. 정책을 숨기지는 않고, 상세 화면에는 원문 그대로 보여 준다.
    const period = (policy.apply_period || "").trim();
    const years = period.match(/20\d\d/g);
    const past = years && years.every((y) => Number(y) < new Date().getFullYear());
    if (period && !past && period.length <= 30 && !/^(상시신청|접수기관 별 상이|연중)$/.test(period)) {
      card.append(el("p", "period", "신청 기간: " + period));
    }

    const actions = el("div", "row actions");
    const detail = el("a", "btn btn-primary", "자세히 보기");
    detail.href = "policy.html?id=" + encodeURIComponent(policy.id);
    actions.append(detail);
    const url = safeUrl(policy.url);
    if (url) {
      const origin = el("a", "btn", "원문 보기");
      origin.href = url;
      origin.target = "_blank";
      origin.rel = "noopener";
      actions.append(origin);
    }
    card.append(actions);
    card.append(el("p", "muted foot", "자격은 신청하는 곳에서 최종 확인해 주세요. · 자료 기준일 " + policy.collected_at));
    return card;
  }

  // ---------- 가족에게 공유 ----------

  // 공유 링크에는 조건값과 정책 ID만 담는다. 대화 내용이나 입력한 문장은 넣지 않는다.
  function shareUrl(conditions, ids) {
    const params = new URLSearchParams();
    if (conditions && conditions.age_group) params.set("age", conditions.age_group);
    if (conditions && conditions.region_code) params.set("region", conditions.region_code);
    params.set("ids", ids.slice(0, 10).join(","));
    return new URL("share.html?" + params.toString(), location.href).href;
  }

  // 공유 창이 되면 그걸 쓰고, 안 되면 주소를 복사한다. 결과 안내 문구를 돌려준다.
  async function share(conditions, ids) {
    const url = shareUrl(conditions, ids);
    if (navigator.share) {
      try {
        await navigator.share({ title: "SPOT에서 찾은 정부 지원", text: "확인해 볼 만한 지원을 찾았어요.", url });
        return "";
      } catch (e) {
        if (e && e.name === "AbortError") return "";   // 사용자가 공유 창을 닫음
      }
    }
    try {
      await navigator.clipboard.writeText(url);
      return "주소를 복사했어요. 문자나 카카오톡에 붙여 넣어 보내 주세요.";
    } catch (e) {
      window.prompt("아래 주소를 길게 눌러 복사해 주세요.", url);
      return "";
    }
  }

  // ---------- 주민센터에서 보여주기 ----------

  // 정책명·신청하는 곳·문의처만 아주 큰 글씨로 보여 준다.
  async function showForOffice(ids) {
    const overlay = el("div", "office");
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-label", "주민센터에서 보여주기");
    const close = () => {
      overlay.remove();
      document.body.classList.remove("no-scroll");
    };
    const body = el("div", "office-body");
    overlay.append(el("p", "office-title", "이 지원을 알아보러 왔어요"), body, button("닫기", close, "btn btn-primary"));
    document.body.append(overlay);
    document.body.classList.add("no-scroll");

    const stop = showLoading(body);
    try {
      const policies = await Promise.all(ids.map((id) => api.get("/api/policy/" + encodeURIComponent(id))));
      stop();
      body.replaceChildren();
      policies.forEach((p, i) => {
        const item = el("section", "office-item");
        item.append(el("h2", "", i + 1 + ". " + p.name));
        item.append(el("p", "", "신청하는 곳: " + (p.apply_place || p.agency || "주민센터에 문의")));
        if (p.apply_period) item.append(el("p", "", "신청 기간: " + p.apply_period.slice(0, 60)));
        const contact = (p.contact || "").split("||").map((s) => s.trim().replace("/", " ")).filter(Boolean).slice(0, 2);
        if (contact.length) item.append(el("p", "", "문의: " + contact.join(", ")));
        body.append(item);
      });
    } catch (e) {
      stop();
      showError(body, e.message);
    }
  }

  // 결과 아래에 붙이는 [가족에게 공유] [주민센터에서 보여주기] 버튼
  function resultActions(conditions, ids) {
    const box = el("div", "stack result-actions");
    const note = el("p", "muted");
    note.setAttribute("aria-live", "polite");
    box.append(
      button("가족에게 공유", async () => { note.textContent = await share(conditions, ids); }, "btn"),
      button("주민센터에서 보여주기", () => showForOffice(ids), "btn"),
      note,
    );
    return box;
  }

  // ---------- 소리로 듣기 (브라우저의 Web Speech API) ----------
  // 기기에 있는 목소리로 읽으므로 서버나 바깥 서비스로 글을 보내지 않는다.
  // 지원하지 않는 브라우저에서는 버튼을 만들지 않는다 (null 을 돌려준다).

  const canSpeak = "speechSynthesis" in window && "SpeechSynthesisUtterance" in window;
  let speakingButton = null;   // 지금 읽고 있는 버튼 (한 번에 하나만 읽는다)

  function koreanVoice() {
    return speechSynthesis.getVoices().find((v) => /^ko/i.test(v.lang)) || null;
  }

  function stopSpeaking() {
    if (!canSpeak) return;
    speechSynthesis.cancel();
    if (speakingButton) speakingButton.textContent = "소리로 듣기";
    speakingButton = null;
  }

  // 읽기 전에 글을 다듬는다. 정책 자료의 기호(■, ○, ㅇ, - 등)를 그대로 넘기면
  // 기기에 따라 "검은 네모", "물결"처럼 소리 내어 읽는다.
  function speakable(text) {
    return String(text || "")
      .split("\n")
      .map((line) => line
        .replace(/^\s*(?:[-*·ㆍ•]|ㅇ(?=\s)|\d+\.(?=\s))\s*/, "")   // 줄 앞의 글머리 기호 ("- 신분증", "ㅇ 공통서류")
        .replace(/[■□▪▫●○◎◆◇▶▷►※★☆]/g, " ")
        .replace(/(^|\s)ㅇ(?=\s)/g, "$1")   // 줄 가운데의 "ㅇ" 글머리 ("준비할 서류: ㅇ 공통서류")
        .replace(/\|\|/g, ", ")
        .replace(/\s*~\s*/g, "부터 ")
        .replace(/\s+/g, " ")
        .trim())
      .filter((line) => line)
      // 줄이 바뀌는 곳에서 조금 쉬어 읽도록 문장 끝 표시를 붙인다
      .map((line) => (/[.?!,:]$/.test(line) ? line : line + "."))
      .join(" ");
  }

  // getText: 누를 때 읽을 글을 돌려주는 함수
  function speakButton(getText, className) {
    if (!canSpeak) return null;
    const node = button("소리로 듣기", () => {
      const wasMe = speakingButton === node;
      stopSpeaking();
      if (wasMe) return;   // 읽는 중에 다시 누르면 멈춘다
      const voices = speechSynthesis.getVoices();
      const voice = koreanVoice();
      if (voices.length > 0 && !voice) {
        node.textContent = "이 기기에는 한국어 목소리가 없어요";
        return;
      }
      const talk = new SpeechSynthesisUtterance(speakable(getText()));
      talk.lang = "ko-KR";
      if (voice) talk.voice = voice;
      talk.rate = 0.9;   // 조금 천천히
      talk.onend = talk.onerror = () => { if (speakingButton === node) stopSpeaking(); };
      speakingButton = node;
      node.textContent = "그만 듣기";
      speechSynthesis.speak(talk);
    }, className || "btn btn-quiet speak");
    return node;
  }

  // 다른 화면으로 가면 읽던 것을 멈춘다
  window.addEventListener("pagehide", stopSpeaking);

  window.SPOT = { api, el, button, safeUrl, showLoading, showError, policyCard, share, showForOffice, resultActions, speakButton, realText };
})();
