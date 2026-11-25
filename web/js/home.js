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

  // 이번 달 많이 본 지원 (정책 상세 화면이 열린 횟수로 매달 새로 센다). 못 받으면 예시 낱말을 그대로 둔다.
  const list = document.getElementById("ranking");
  const periodText = document.getElementById("ranking-period");
  function shortDate(iso) {
    const [, m, d] = iso.split("-");
    return Number(m) + "." + Number(d);
  }
  fetch("/api/ranking")
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      if (!data || !data.items || data.items.length === 0) return;
      list.replaceChildren();
      data.items.forEach((item, i) => {
        const li = document.createElement("li");
        const a = document.createElement("a");
        a.href = "policy.html?id=" + encodeURIComponent(item.id);
        const rank = document.createElement("span");
        rank.className = "rank";
        rank.textContent = String(i + 1);
        a.append(rank, document.createTextNode(item.name));
        li.append(a);
        list.append(li);
      });
      periodText.textContent = shortDate(data.period_start) + " ~ " + shortDate(data.period_end) +
        " · [자세히 보기]를 많이 누른 순서예요";
      periodText.hidden = false;
    })
    .catch(() => {});
})();
