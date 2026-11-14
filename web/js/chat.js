// 채팅 화면. 대화 내용은 이 화면의 변수에만 두고 어디에도 저장하지 않는다 (새로 고치면 사라진다).
(function () {
  "use strict";
  const { api, el, button, policyCard, resultActions } = window.SPOT;

  const log = document.getElementById("log");
  const form = document.getElementById("form");
  const input = document.getElementById("message");
  const sendButton = document.getElementById("send");

  const EXAMPLES = [
    "허리가 아파서 병원에 가려는데 지원받을 수 있는 게 있나요?",
    "혼자 사는데 겨울 난방비가 걱정이에요",
    "아이를 낳았는데 받을 수 있는 지원금이 있나요?",
  ];
  const HISTORY_LIMIT = 6;

  // 서버는 대화를 기억하지 않으므로, 조건과 최근 대화를 여기서 들고 있다가 매번 같이 보낸다.
  let conditions = { age_group: null, gender: null, region_code: null, household: null, need: null, search_text: null };
  let history = [];
  let asked = false;
  let options = null;
  let busy = false;

  function scrollDown() {
    window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
  }

  function bubble(who, text) {
    const node = el("div", "bubble " + who, text);
    log.append(node);
    scrollDown();
    return node;
  }

  function remember(role, text) {
    history.push({ role, text });
    history = history.slice(-HISTORY_LIMIT);
  }

  function setBusy(on) {
    busy = on;
    sendButton.disabled = on;
    input.disabled = on;
  }

  // ---------- 서버 호출 ----------

  async function call(message) {
    setBusy(true);
    const waiting = bubble("bot waiting", "찾고 있어요…");
    const slow = setTimeout(() => {
      waiting.textContent = "찾고 있어요… 처음에는 1분쯤 걸릴 수 있어요.";
    }, 6000);
    let data;
    try {
      data = await api.post("/api/chat", { message, conditions, history, asked });
    } catch (e) {
      clearTimeout(slow);
      waiting.remove();
      bubble("bot", e.message);
      setBusy(false);
      return;
    }
    clearTimeout(slow);
    waiting.remove();
    setBusy(false);
    if (message) remember("user", message);
    show(data);
  }

  function show(data) {
    if (data.conditions) conditions = Object.assign(conditions, data.conditions);
    bubble("bot", data.text);
    remember("assistant", data.text);

    if (data.type === "ask") {
      asked = true;
      askNext(data.ask.slice());
      return;
    }
    if (data.type === "result") {
      const box = el("div", "stack results");
      data.policies.forEach((p) => box.append(policyCard(p)));
      box.append(resultActions(conditions, data.policies.map((p) => p.id)));
      log.append(box);
      bubble("bot", "더 궁금한 점이 있으면 아래에 적어 주세요.");
      return;
    }
    if (data.type === "fallback") {
      // AI 답변이 안 될 때: 지금까지 고른 조건을 들고 버튼 조회로 간다
      const params = new URLSearchParams({ result: "1" });
      ["age_group", "gender", "region_code", "household"].forEach((key) => {
        if (conditions[key]) params.set(key, conditions[key]);
      });
      const link = el("a", "btn btn-primary", "버튼으로 찾기");
      link.href = "search.html?" + params.toString();
      log.append(link);
      scrollDown();
    }
  }

  // ---------- 되묻기 (버튼으로 고르기) ----------

  // 묻는 항목을 하나씩 보여 주고, 다 고르면 질문 없이 조건만 다시 보낸다.
  async function askNext(items) {
    if (items.length === 0) {
      call("");
      return;
    }
    const item = items.shift();
    if (!options) {
      try {
        options = await api.get("/api/options");
      } catch (e) {
        bubble("bot", e.message);
        return;
      }
    }
    if (item === "age_group") {
      pick("나이대를 골라 주세요", options.age_group.map((o) => [o.value, o.label]), (value, label) => {
        conditions.age_group = value;
        if (label) bubble("user", label);
        askNext(items);
      });
    } else {
      pickRegion(() => askNext(items));
    }
  }

  // 선택지 묶음을 대화 아래에 붙인다. 고르면 묶음은 사라지고 고른 값이 말풍선으로 남는다.
  function pick(title, items, onPick) {
    const box = el("div", "picker");
    box.append(el("p", "picker-title", title));
    const list = el("div", items.length > 6 ? "options-scroll" : "stack");
    items.forEach(([value, label]) => {
      list.append(button(label, () => { box.remove(); onPick(value, label); }));
    });
    box.append(list);
    box.append(button("잘 모르겠어요 / 건너뛰기", () => { box.remove(); onPick(null, null); }, "btn btn-quiet"));
    log.append(box);
    scrollDown();
  }

  function pickRegion(done) {
    pick("사시는 곳(시·도)을 골라 주세요", options.sido.map((o) => [o.code, o.name]), async (sido, sidoName) => {
      if (!sido) {
        done();
        return;
      }
      conditions.region_code = sido;
      let regions = [];
      try {
        regions = (await api.get("/api/regions?sido=" + sido)).regions;
      } catch (e) {
        // 시·군·구 목록을 못 받아도 시·도만으로 계속한다
      }
      if (regions.length === 0) {   // 세종·제주는 시·군·구가 없다
        bubble("user", sidoName);
        done();
        return;
      }
      pick("사시는 곳(시·군·구)을 골라 주세요", regions.map((o) => [o.code, o.name]), (code, name) => {
        if (code) conditions.region_code = code;
        bubble("user", name ? sidoName + " " + name : sidoName);
        done();
      });
    });
  }

  // ---------- 질문 보내기 ----------

  function send(text) {
    const message = text.trim();
    if (!message || busy) return;
    document.querySelectorAll(".picker, .examples").forEach((node) => node.remove());
    bubble("user", message);
    input.value = "";
    call(message);
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    send(input.value);
  });

  // Enter 로 보내기 (Shift+Enter 는 줄 바꿈). 한글을 조합하는 중에는 보내지 않는다.
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      send(input.value);
    }
  });

  // ---------- 시작 ----------

  bubble("bot", "안녕하세요. 어떤 도움이 필요하신지 편하게 말씀해 주세요. 받을 수 있는 지원을 찾아 드릴게요.\n이름이나 전화번호는 적지 않으셔도 돼요.");
  const examples = el("div", "examples stack");
  examples.append(el("p", "muted", "이렇게 물어보실 수 있어요. 눌러 보세요."));
  EXAMPLES.forEach((text) => examples.append(button(text, () => send(text), "btn btn-quiet example")));
  log.append(examples);
})();
