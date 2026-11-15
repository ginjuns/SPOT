// 직접 찾기: 낱말, 분야, 내 조건(나이대 → 성별 → 시·도 → 시·군·구 → 가구 형태)으로 찾고 결과를 본다.
// 조건은 한 단계씩 고른다. 결과 화면에서는 낱말과 분야로 더 좁힐 수 있다. AI는 쓰지 않는다.
(function () {
  "use strict";
  const { api, el, showLoading, showError, policyCard } = window.SPOT;
  const KEYWORD_LIMIT = 50;

  const main = document.getElementById("main");
  const backButton = document.getElementById("back");

  const STEPS = ["category", "age_group", "gender", "sido", "sigungu", "household"];
  const QUESTIONS = {
    category: "어떤 도움을 찾으세요?",
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
  // 결과를 좁히는 값: 검색창에 적은 낱말과 분야. 조건을 다시 골라도 그대로 둔다.
  const filters = { q: "", category: null, org: false };   // org: 기업·단체가 받는 지원도 볼지

  function hasCondition() {
    return STEPS.some((key) => chosen[key]);
  }

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
    // 분야는 결과 화면에서도 바꿀 수 있어서 filters 에 둔다 (건너뛰면 모든 분야)
    if (key === "category") {
      filters.category = value;
      next();
      return;
    }
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

  // 결과 화면은 컴퓨터에서 넓게 쓰고(왼쪽 칸 + 카드 여러 줄), 조건 고르기는 좁게 가운데에 둔다
  function setWide(on) {
    main.classList.toggle("results", on);
    main.parentElement.classList.toggle("wide", on);
  }

  function renderStep() {
    setWide(false);
    const key = STEPS[step];
    const items = {
      category: () => options.category.map((o) => [o.value, o.label]),
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
    const skipLabel = key === "category" ? "모든 분야에서 찾기" : "잘 모르겠어요 / 건너뛰기";
    const skip = optionButton(skipLabel, () => choose(key, null, null), "btn btn-quiet");
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
      category: filters.category,
      q: filters.q || null,
      include_org: filters.org,
    };
  }

  // 결과 화면 주소에 조건을 담아 둔다. 상세 화면에서 뒤로 왔을 때 결과를 다시 보여 주기 위해서다.
  function rememberInAddress() {
    const params = new URLSearchParams();
    const cond = conditions();
    Object.keys(cond).forEach((key) => {
      if (cond[key] && key !== "q" && key !== "include_org") params.set(key, cond[key]);
    });
    if (filters.org) params.set("org", "1");
    params.set("result", "1");
    // 적은 낱말은 # 뒤에 둔다 (서버로 전송되지 않아 서버 기록에 남지 않는다)
    const hash = filters.q ? "#q=" + encodeURIComponent(filters.q) : "";
    history.replaceState(null, "", "search.html?" + params.toString() + hash);
  }

  // 결과 위에 두는 검색창과 분야 고르기. 바꾸면 결과를 다시 찾는다.
  function filterBox() {
    const box = el("div", "filter-box");

    const form = el("form", "search-form");
    const input = el("input");
    input.type = "search";
    input.maxLength = KEYWORD_LIMIT;
    input.placeholder = "이름이나 낱말";
    input.setAttribute("aria-label", "이름이나 낱말로 찾기");
    input.setAttribute("enterkeyhint", "search");
    input.autocomplete = "off";
    input.value = filters.q;
    const submit = el("button", "btn btn-primary", "찾기");
    submit.type = "submit";
    form.append(input, submit);
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      filters.q = input.value.trim();
      showResults(true);
    });

    const label = el("label", "field");
    label.append(el("span", "field-name", "분야"));
    const select = el("select");
    select.append(new Option("모든 분야", ""));
    options.category.forEach((o) => select.append(new Option(o.label, o.value)));
    select.value = filters.category || "";
    select.addEventListener("change", () => {
      filters.category = select.value || null;
      showResults(true);
    });
    label.append(select);

    // 컴퓨터 화면에서는 펼침 목록 대신 분야를 모두 늘어놓는다 (어느 쪽을 보일지는 CSS가 정한다)
    const cats = el("div", "cat-list");
    cats.append(el("p", "field-name", "분야"));
    [["", "모든 분야"]].concat(options.category.map((o) => [o.value, o.label])).forEach(([value, name]) => {
      const on = (filters.category || "") === value;
      const item = optionButton(name, () => {
        filters.category = value || null;
        showResults(true);
      }, on ? "btn cat on" : "btn cat");
      item.setAttribute("aria-pressed", on ? "true" : "false");
      cats.append(item);
    });

    // 기본으로는 개인·가구가 받는 지원만 보여 준다. 표시하면 기업·단체가 받는 지원도 함께 본다.
    const org = el("label", "check");
    const box2 = el("input");
    box2.type = "checkbox";
    box2.checked = filters.org;
    box2.addEventListener("change", () => {
      filters.org = box2.checked;
      showResults(true);
    });
    org.append(box2, el("span", "", "기업·단체가 받는 지원도 보기"));

    box.append(form, label, cats, org);
    return box;
  }

  async function showResults(remember) {
    step = STEPS.length;
    if (remember) rememberInAddress();
    let page = 1;
    let shown = 0;

    const list = el("div", "stack cards");
    const status = el("div");
    const more = optionButton("더 보기", loadPage, "btn btn-primary");
    more.hidden = true;
    const again = optionButton(hasCondition() ? "조건 다시 고르기" : "내 조건 고르기 (나이대, 사는 곳)", restart, "btn");

    // 좁히는 도구(검색창, 분야, 조건)는 한 묶음으로 둔다. 컴퓨터 화면에서는 왼쪽 칸이 된다.
    const side = el("aside", "filters");
    side.append(filterBox(), chosenList(), again);
    const title = el("h1", "", "찾은 지원");
    setWide(true);
    main.replaceChildren(title, side, list, status, more);
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
        if (data.hidden_org) {
          status.append(el("p", "", "기업·단체가 받는 지원은 " + data.hidden_org.toLocaleString("ko-KR") + "건이 있어요. 위의 \"기업·단체가 받는 지원도 보기\"에 표시하면 볼 수 있어요."));
        }
        status.append(el("p", "", (filters.q ? "낱말을 바꾸거나 " : "") + "조건을 줄여서 다시 찾아보시거나, 가까운 주민센터나 보건복지상담센터(국번 없이 129)에 물어보시면 도움을 받을 수 있어요."));
        return;
      }
      title.textContent = "지원 " + data.total.toLocaleString("ko-KR") + "건을 찾았어요";
      status.append(el("p", "muted", data.total.toLocaleString("ko-KR") + "건 중 " + shown.toLocaleString("ko-KR") + "건을 보고 있어요."));
      if (data.related && data.related.length) {
        status.append(el("p", "muted", "비슷한 말인 '" + data.related.join("', '") + "'(으)로도 함께 찾았어요."));
      }
      if (data.hidden_org) {
        status.append(el("p", "muted", "기업·단체가 받는 지원 " + data.hidden_org.toLocaleString("ko-KR") + "건은 빼고 보여 드렸어요."));
      }
      if (!regionCode()) {
        status.append(el("p", "muted", filters.q
          ? "사시는 곳을 고르지 않아서 모든 지역의 지원을 보여 드렸어요. 카드에 적힌 기관 이름을 확인해 주세요."
          : "사시는 곳을 고르지 않아서 전국 지원만 보여 드렸어요. 조건을 고르면 사시는 지역의 지원도 볼 수 있어요."));
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
    // 결과 화면에서 이미 분야를 골랐으면 분야 단계는 건너뛴다 ([← 뒤로]로 돌아가 바꿀 수 있다)
    step = filters.category ? 1 : 0;
    history.replaceState(null, "", "search.html");
    renderStep();
  }

  // ---------- 뒤로 ----------

  backButton.addEventListener("click", () => {
    // 첫 단계이거나, 조건을 고르지 않고 낱말·분야만으로 온 결과 화면이면 시작 화면으로 간다
    if (step === 0 || (step >= STEPS.length && !hasCondition())) {
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
    const category = find(options.category, "value", params.get("category"));
    if (category) filters.category = category.value;
    filters.org = params.get("org") === "1";
    const q = new URLSearchParams(location.hash.slice(1)).get("q") || "";
    filters.q = q.trim().slice(0, KEYWORD_LIMIT);
    const age =find(options.age_group, "value", params.get("age_group"));
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
