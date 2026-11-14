// 공유 링크로 열었을 때의 결과 화면. 주소에는 조건값(age, region)과 정책 ID(ids)만 들어 있다.
(function () {
  "use strict";
  const { api, el, showLoading, showError, policyCard, resultActions } = window.SPOT;

  const main = document.getElementById("main");
  const params = new URLSearchParams(location.search);
  const ids = (params.get("ids") || "").split(",").map((s) => s.trim()).filter(Boolean).slice(0, 10);
  const conditions = { age_group: params.get("age"), region_code: params.get("region") };

  // 조건을 "75세 이상", "서울특별시 강남구"처럼 읽을 수 있는 말로 바꾼다. 못 바꾸면 보여 주지 않는다.
  async function conditionLabels() {
    const labels = [];
    try {
      const options = await api.get("/api/options");
      const age = options.age_group.find((o) => o.value === conditions.age_group);
      if (age) labels.push(age.label);
      const region = conditions.region_code || "";
      const sido = options.sido.find((o) => o.code === region.slice(0, 2));
      if (sido) {
        let name = sido.name;
        if (region.length === 5) {
          const regions = (await api.get("/api/regions?sido=" + sido.code)).regions;
          const sigungu = regions.find((o) => o.code === region);
          if (sigungu) name += " " + sigungu.name;
        }
        labels.push(name);
      }
    } catch (e) {
      // 조건 이름은 없어도 된다
    }
    return labels;
  }

  async function start() {
    if (ids.length === 0) {
      showError(main, "공유받은 주소가 올바르지 않아요. 보내 주신 분께 다시 받아 주세요.");
      return;
    }
    const stop = showLoading(main);
    let data, labels;
    try {
      [data, labels] = await Promise.all([
        api.get("/api/policies?ids=" + encodeURIComponent(ids.join(","))),
        conditionLabels(),
      ]);
    } catch (e) {
      stop();
      showError(main, e.message, start);
      return;
    }
    stop();
    if (data.policies.length === 0) {
      showError(main, "공유받은 지원을 찾지 못했어요. 지원이 끝났을 수 있어요.");
      return;
    }

    const parts = [
      el("h1", "", "가족이 찾은 지원 " + data.policies.length + "건이에요"),
      el("p", "lead", "확인해 볼 만한 지원이에요. [자세히 보기]를 누르면 신청 방법과 문의처를 볼 수 있어요."),
    ];
    if (labels.length) {
      const chosen = el("ul", "chosen");
      labels.forEach((label) => chosen.append(el("li", "", label)));
      parts.push(chosen);
    }
    const list = el("div", "stack");
    data.policies.forEach((p) => list.append(policyCard(p)));
    list.append(resultActions(conditions, data.policies.map((p) => p.id)));
    parts.push(list);
    main.replaceChildren(...parts);
  }

  start();
})();
