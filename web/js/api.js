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
    if (onRetry) {
      const retry = el("button", "btn btn-primary", "다시 해 보기");
      retry.type = "button";
      retry.addEventListener("click", onRetry);
      box.append(retry);
    }
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

  window.SPOT = { api, el, safeUrl, showLoading, showError, policyCard };
})();
