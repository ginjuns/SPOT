// 글씨 크기 설정. 모든 화면의 <head>에서 먼저 불러서, 화면이 그려지기 전에 적용한다.
// 설정만 localStorage 에 저장한다 (대화 내용은 저장하지 않는다). 저장이 막혀 있어도 동작한다.
// (또렷한 화면(고대비)은 2026-11-18에 사용자 요청으로 뺐다)
(function () {
  "use strict";
  const KEYS = { size: "spot-size", oldBig: "spot-big" };
  const root = document.documentElement;

  // 글씨 크기 단계. 실제 크기는 style.css 의 html[data-size] 규칙 (18px · 20px · 22px · 24px)
  const SIZE_NAMES = ["보통", "조금 크게", "크게", "가장 크게"];
  const MAX_SIZE = SIZE_NAMES.length - 1;

  function load(key) {
    try {
      return localStorage.getItem(key);
    } catch (e) {
      return null;
    }
  }

  function save(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch (e) {
      // 저장이 안 되면 이번 화면에서만 적용된다
    }
  }

  function readSize() {
    const saved = parseInt(load(KEYS.size), 10);
    if (saved >= 0 && saved <= MAX_SIZE) return saved;
    return load(KEYS.oldBig) === "1" ? MAX_SIZE : 0;   // 예전 [큰 글씨]를 켜 두었던 사람은 가장 크게
  }

  function applySize(level) {
    if (level > 0) root.setAttribute("data-size", String(level));
    else root.removeAttribute("data-size");
  }

  // 설정이 바뀌었음을 알린다 (컴퓨터의 작은 채팅 창이 똑같이 맞추도록, js/fab.js)
  function changed() {
    document.dispatchEvent(new Event("spot-settings"));
  }

  let size = readSize();
  applySize(size);

  // 홈 화면에 추가(PWA)를 위한 서비스 워커 등록. 지원하지 않는 브라우저에서는 그냥 넘어간다.
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("service-worker.js").catch(() => {});
    });
  }

  // 글씨 크기 버튼과 지금 단계 표시를 모두 맞춘다 (시작 화면과 위쪽 메뉴에 같은 버튼이 있을 수 있다)
  function showSize() {
    document.querySelectorAll("[data-font]").forEach((button) => {
      const up = button.getAttribute("data-font") === "up";
      button.disabled = up ? size >= MAX_SIZE : size <= 0;
    });
    document.querySelectorAll(".font-level").forEach((node) => {
      node.textContent = SIZE_NAMES[size];
    });
  }

  // 버튼은 화면 안 어디에 있든(나중에 만들어진 위쪽 메뉴 포함) 여기서 한 번에 받는다
  //   <button data-font="down">작게</button> <span class="font-level"></span> <button data-font="up">크게</button>
  document.addEventListener("click", (event) => {
    const fontButton = event.target.closest("[data-font]");
    if (!fontButton) return;
    const next = size + (fontButton.getAttribute("data-font") === "up" ? 1 : -1);
    if (next < 0 || next > MAX_SIZE) return;
    size = next;
    applySize(size);
    save(KEYS.size, String(size));
    showSize();
    changed();
  });

  document.addEventListener("DOMContentLoaded", () => {
    showSize();

    // 인터넷이 끊기면 화면 위에 알린다. 다시 연결되면 저절로 사라진다.
    const banner = document.createElement("p");
    banner.className = "offline-banner";
    banner.setAttribute("role", "status");
    banner.textContent = "인터넷이 끊겼어요. 연결되면 다시 찾을 수 있어요.";
    const showBanner = () => {
      if (navigator.onLine) banner.remove();
      else if (!banner.isConnected) document.body.prepend(banner);
    };
    window.addEventListener("online", showBanner);
    window.addEventListener("offline", showBanner);
    showBanner();
  });
})();
