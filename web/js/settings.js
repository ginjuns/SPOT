// 큰 글씨·고대비 설정. 모든 화면의 <head>에서 먼저 불러서, 화면이 그려지기 전에 적용한다.
// 설정만 localStorage 에 저장한다 (대화 내용은 저장하지 않는다). 저장이 막혀 있어도 동작한다.
(function () {
  "use strict";
  const KEYS = { big: "spot-big", contrast: "spot-contrast" };
  const root = document.documentElement;

  function read(name) {
    try {
      return localStorage.getItem(KEYS[name]) === "1";
    } catch (e) {
      return false;
    }
  }

  function apply(name, on) {
    if (on) root.setAttribute("data-" + name, "1");
    else root.removeAttribute("data-" + name);
  }

  function set(name, on) {
    apply(name, on);
    try {
      localStorage.setItem(KEYS[name], on ? "1" : "0");
    } catch (e) {
      // 저장이 안 되면 이번 화면에서만 적용된다
    }
  }

  apply("big", read("big"));
  apply("contrast", read("contrast"));

  // 시작 화면의 전환 버튼: <button data-setting="big"> 처럼 쓴다
  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-setting]").forEach((button) => {
      const name = button.getAttribute("data-setting");
      const show = () => {
        const on = root.hasAttribute("data-" + name);
        button.setAttribute("aria-pressed", on ? "true" : "false");
        button.querySelector(".state").textContent = on ? "켜짐" : "꺼짐";
      };
      button.addEventListener("click", () => {
        set(name, !root.hasAttribute("data-" + name));
        show();
      });
      show();
    });
  });
})();
