// [말로 묻기] 버튼. 휴대폰에서는 채팅 화면으로 이동하고(링크 그대로),
// 컴퓨터처럼 넓은 화면에서는 보던 화면 위에 작은 채팅 창을 띄운다.
(function () {
  "use strict";
  const fab = document.querySelector(".chat-fab");
  if (!fab) return;
  const wide = window.matchMedia("(min-width: 900px)");
  let panel = null;
  let frame = null;

  // 큰 글씨·또렷한 화면 설정을 채팅 창 안에도 똑같이 적용한다
  function syncSettings() {
    try {
      const inner = frame.contentDocument.documentElement;
      ["data-big", "data-contrast"].forEach((name) => {
        if (document.documentElement.hasAttribute(name)) inner.setAttribute(name, "1");
        else inner.removeAttribute(name);
      });
    } catch (e) {
      // 아직 채팅 화면을 불러오는 중이면 넘어간다 (불러온 뒤 load 에서 다시 맞춘다)
    }
  }

  function close() {
    panel.hidden = true;
    fab.hidden = false;
    fab.focus();
  }

  function build() {
    panel = document.createElement("div");
    panel.className = "chat-panel";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", "말로 묻기");

    const head = document.createElement("div");
    head.className = "chat-panel-head";
    const title = document.createElement("span");
    title.textContent = "말로 묻기";
    const closeButton = document.createElement("button");
    closeButton.type = "button";
    closeButton.className = "hero-pill";
    closeButton.textContent = "닫기";
    closeButton.addEventListener("click", close);
    head.append(title, closeButton);

    // 채팅 화면을 그대로 창 안에 넣는다. 창을 닫아도 대화는 이 화면을 떠날 때까지 남아 있다.
    frame = document.createElement("iframe");
    frame.title = "말로 묻기";
    frame.src = "chat.html";
    frame.addEventListener("load", syncSettings);

    panel.append(head, frame);
    document.body.append(panel);
  }

  fab.addEventListener("click", (event) => {
    if (!wide.matches) return;   // 휴대폰: 채팅 화면으로 이동
    event.preventDefault();
    if (!panel) build();
    panel.hidden = false;
    fab.hidden = true;
    syncSettings();
  });
})();
