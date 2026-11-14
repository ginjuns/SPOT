// 버튼 조회: 나이대 → 성별 → 시·도 → 시·군·구 → 가구 형태를 한 단계씩 고르고 결과를 본다.
(function () {
  "use strict";
  const { api, el, showLoading, showError, policyCard } = window.SPOT;

  const main = document.getElementById("main");
  const backButton = document.getElementById("back");

  const STEPS = ["age_group", "gender", "sido", "sigungu", "household"];
  const QUESTIONS = {
    age_group: "나이대를 골라 주세요",
    gender: "성별을 골라 주세요",
    sido: "사시는 곳(시·도)을 골라 주세요",
    sigungu: "사시는 곳(시·군·구)을 골라 주세요",
    household: "해당하는 것이 있으면 골라 주세요",
  };

  let options = null;      // /api/options 응답
  let sigunguList = [];    // 고른 시·도의 시·군·구 목록
  let step = 0;
  // 고른 값. 고르지 않은 것은 null 로 둔다.
  const chosen = { age_group: null, gender: null, sido: null, sigungu: null, household: null };
  const labels = {};       // 화면에 보여 줄 이름 (예: "75세 이상")

  function regionCode() {
    return chosen.sigungu || chosen.sido || null;
  }

  // ---------- 조건 고르기 ----------

  function chosenList() {
    const list = el("ul", "chosen");
    STEPS.forEach((key) => {
      if (labels[key]) list.append(el("li", "", labels[key]));
    });
    return list;
  }

  function optionButton(label, onClick, className) {
    const button = el("button", className || "btn", label);
    button.type = "button";
    button.addEventListener("click", onClick);
    return button;
  }

  function choose(key, value, label) {
    chosen[key] = value;
    if (label) labels[key] = label;
    else delete labels[key];
    next();
  }

  async function next() {
    const key = STEPS[step];
    if (key === "sido") {
      // 시·도를 바꾸면 전에 고른 시·군·구는 지운다
      chosen.sigungu = null;
      delete labels.sigungu;
      sigunguList = [];
      if (chosen.sido) {
        const stop = showLoading(main);
        try {
          sigunguList = (await api.get("/api/regions?sido=" + chosen.sido)).regions;
        } catch (e) {
          stop();
          showError(main, e.message, next);
          return;
        }
        stop();
      }
    }
    step += 1;
    // 세종·제주처럼 시·군·구가 없거나 시·도를 건너뛰었으면 시·군·구 단계도 건너뛴다
    if (STEPS[step] === "sigungu" && sigunguList.length === 0) step += 1;
    if (step >= STEPS.length) showResults(true);
    else renderStep();
  }

  function renderStep() {
    const key = STEPS[step];
    const items = {
      age_group: () => options.age_group.map((o) => [o.value, o.label]),
      gender: () => options.gender.map((o) => [o.value, o.label]),
      sido: () => options.sido.map((o) => [o.code, o.name]),
      sigungu: () => sigunguList.map((o) => [o.code, o.name]),
      household: () => options.household.map((o) => [o.value, o.label]),
    }[key]();

    const many = items.length > 6;   // 한 화면의 선택지는 6개까지, 넘으면 스크롤 목록
    const box = el("div", many ? "options-scroll" : "stack");
    items.forEach(([value, label]) => box.append(optionButton(label, () => choose(key, value, label))));

    main.replaceChildren(
      el("p", "step-count", step + 1 + " / " + STEPS.length + " 단계"),
      el("h1", "", QUESTIONS[key]),
      chosenList(),
      box,
    );
    if (many) main.append(el("p", "muted", "목록을 위아래로 밀어서 찾아 주세요."));
    const skip = optionButton("잘 모르겠어요 / 건너뛰기", () => choose(key, null, null), "btn btn-quiet");
    skip.style.marginTop = "12px";
    main.append(skip);
    window.scrollTo(0, 0);
  }

  // ---------- 결과 ----------

  function conditions() {
    return {
      age_group: chosen.age_group,
      gender: chosen.gender,
      region_code: regionCode(),
      household: chosen.household,
    };
  }

  // 결과 화면 주소에 조건을 담아 둔다. 상세 화면에서 뒤로 왔을 때 결과를 다시 보여 주기 위해서다.
  function rememberInAddress() {
    const params = new URLSearchParams();
    const cond = conditions();
    Object.keys(cond).forEach((key) => {
      if (cond[key]) params.set(key, cond[key]);
    });
    params.set("result", "1");
    history.replaceState(null, "", "search.html?" + params.toString());
  }

  async function showResults(remember) {
    step = STEPS.length;
    if (remember) rememberInAddress();
    let page = 1;
    let shown = 0;

    const list = el("div", "stack");
    const status = el("div");
    const more = optionButton("더 보기", loadPage, "btn btn-primary");
    more.hidden = true;
    const again = optionButton("조건 다시 고르기", restart, "btn");

    const title = el("h1", "", "찾은 지원");
    main.replaceChildren(title, chosenList(), list, status, el("div", "stack"));
    main.lastChild.append(more, again);
    window.scrollTo(0, 0);

    async function loadPage() {
      more.hidden = true;
      const stop = showLoading(status);
      let data;
      try {
        data = await api.post("/api/search", Object.assign(conditions(), { page }));
      } catch (e) {
        stop();
        showError(status, e.message, loadPage);
        return;
      }
      stop();
      status.replaceChildren();
      data.policies.forEach((p) => list.append(policyCard(p)));
      shown += data.policies.length;
      page += 1;

      if (data.total === 0) {
        title.textContent = "맞는 지원을 찾지 못했어요";
        status.append(el("p", "", "조건을 줄여서 다시 찾아보시거나, 가까운 주민센터나 보건복지상담센터(국번 없이 129)에 물어보시면 도움을 받을 수 있어요."));
        return;
      }
      title.textContent = "지원 " + data.total.toLocaleString("ko-KR") + "건을 찾았어요";
      status.append(el("p", "muted", data.total.toLocaleString("ko-KR") + "건 중 " + shown.toLocaleString("ko-KR") + "건을 보고 있어요."));
      if (!regionCode()) {
        status.append(el("p", "muted", "사시는 곳을 고르지 않아서 전국 지원만 보여 드렸어요."));
      }
      more.hidden = shown >= data.total;
    }

    loadPage();
  }

  function restart() {
    STEPS.forEach((key) => {
      chosen[key] = null;
      delete labels[key];
    });
    sigunguList = [];
    step = 0;
    history.replaceState(null, "", "search.html");
    renderStep();
  }

  // ---------- 뒤로 ----------

  backButton.addEventListener("click", () => {
    if (step === 0) {
      location.href = "index.html";
      return;
    }
    if (step >= STEPS.length) history.replaceState(null, "", "search.html");
    step -= 1;
    if (STEPS[step] === "sigungu" && sigunguList.length === 0) step -= 1;
    const key = STEPS[step];
    chosen[key] = null;
    delete labels[key];
    renderStep();
  });

  // ---------- 시작 ----------

  // 주소에 조건이 담겨 있으면(상세 화면에서 돌아온 경우) 고른 값을 되살린다.
  async function restoreFromAddress(params) {
    const find = (list, key, value) => list.find((o) => o[key] === value);
    const age = find(options.age_group, "value", params.get("age_group"));
    if (age) { chosen.age_group = age.value; labels.age_group = age.label; }
    const gender = find(options.gender, "value", params.get("gender"));
    if (gender) { chosen.gender = gender.value; labels.gender = gender.label; }
    const household = find(options.household, "value", params.get("household"));
    if (household) { chosen.household = household.value; labels.household = household.label; }

    const region = params.get("region_code") || "";
    const sido = find(options.sido, "code", region.slice(0, 2));
    if (sido) {
      chosen.sido = sido.code;
      labels.sido = sido.name;
      sigunguList = (await api.get("/api/regions?sido=" + sido.code)).regions;
      const sigungu = find(sigunguList, "code", region);
      if (sigungu) { chosen.sigungu = sigungu.code; labels.sigungu = sigungu.name; }
    }
  }

  async function start() {
    const stop = showLoading(main);
    try {
      options = await api.get("/api/options");
      const params = new URLSearchParams(location.search);
      if (params.get("result") === "1") {
        await restoreFromAddress(params);
        stop();
        showResults(false);
        return;
      }
    } catch (e) {
      stop();
      showError(main, e.message, start);
      return;
    }
    stop();
    renderStep();
  }

  start();
})();
