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

  // 정책 카드. 내용은 서버가 준 DB 값을 그대로 보여 준다.
  function policyCard(policy) {
    const card = el("article", "card");
    card.append(el("h2", "", policy.name));
    card.append(el("p", "agency", policy.agency || ""));
    if (policy.has_income_rule) card.append(el("span", "badge", "소득 기준 있음"));
    if (policy.one_line) card.append(el("p", "", policy.one_line));

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

  window.SPOT = { api, el, button, safeUrl, showLoading, showError, policyCard, share, showForOffice, resultActions };
})();
