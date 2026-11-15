// 시작 화면의 검색창. 적은 낱말은 주소의 # 뒤에 담아 결과 화면으로 넘긴다.
// # 뒤의 글은 서버로 전송되지 않으므로 서버 기록에 남지 않는다.
(function () {
  "use strict";
  const form = document.getElementById("search-form");
  const input = document.getElementById("q");

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const q = input.value.trim();
    if (!q) {
      input.focus();
      return;
    }
    location.href = "search.html?result=1#q=" + encodeURIComponent(q);
  });
})();
