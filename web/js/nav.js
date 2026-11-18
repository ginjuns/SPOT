// 컴퓨터 화면(폭 900px 이상)의 위쪽 메뉴. 메뉴 이름에 마우스를 올리면 그 메뉴만 바로 아래에 펼쳐진다.
// 휴대폰에서는 CSS 로 숨긴다 (휴대폰 배치는 바꾸지 않는다).
// 키보드(Tab)로 들어와도 펼쳐지고, Esc 를 누르거나 바깥을 누르면 닫힌다.
(function () {
  "use strict";

  const cat = (value, label) => [label, "search.html?result=1&category=" + encodeURIComponent(value)];
  const word = (q) => [q, "search.html?result=1#q=" + encodeURIComponent(q)];

  // 분야 값과 이름은 data/options.json 의 category 와 같게 둔다
  const MENUS = [
    {
      title: "분야로 찾기",
      wide: true,   // 항목이 많아서 두 줄로 늘어놓는다
      items: [
        cat("생활안정", "생활비"), cat("보건·의료", "병원·건강"), cat("보호·돌봄", "돌봄"),
        cat("주거·자립", "집·주거"), cat("고용·창업", "일자리"), cat("임신·출산", "임신·출산"),
        cat("보육·교육", "아이·교육"), cat("문화·환경", "문화·여가"), cat("행정·안전", "안전·편의"),
        cat("농림축산어업", "농사·어업"),
      ],
    },
    {
      title: "나이로 찾기",
      items: [
        ["조건 하나씩 골라서 찾기", "search.html"],
        ["청년 (19~34세)", "search.html?result=1&age_group=19_34"],
        ["중장년 (50~64세)", "search.html?result=1&age_group=50_64"],
        ["어르신 (65~74세)", "search.html?result=1&age_group=65_74"],
        ["75세 이상", "search.html?result=1&age_group=75plus"],
      ],
    },
    {
      title: "많이 찾는 지원",
      items: [word("기초연금"), word("난방비"), word("병원비"), word("노인일자리"), word("출산"), word("월세")],
    },
    {
      title: "물어보기",
      items: [["궁금한 것 물어보기", "chat.html", "chat"]],
      note: "정책 이름을 몰라도 지금 상황을 말씀하시면 찾아 드려요.",
    },
  ];

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  }

  const header = el("header", "site-nav");
  const inner = el("div", "site-nav-inner");
  const logo = el("a", "site-logo", "SPOT");
  logo.href = "index.html";
  const menu = el("ul", "site-menu");
  const entries = [];   // [메뉴 칸(li), 메뉴 이름 버튼]

  MENUS.forEach((m, index) => {
    const li = el("li", "site-menu-item");
    const top = el("button", "site-menu-btn", m.title);
    top.type = "button";
    top.setAttribute("aria-expanded", "false");
    top.setAttribute("aria-controls", "drop-" + index);

    // 이 메뉴만의 펼침 상자 (메뉴 이름 바로 아래)
    const drop = el("div", "drop" + (m.wide ? " wide" : ""));
    drop.id = "drop-" + index;
    const list = el("ul");
    m.items.forEach(([label, href, kind]) => {
      const item = el("li");
      const link = el("a", "", label);
      link.href = href;
      if (kind === "chat") link.dataset.chat = "1";
      item.append(link);
      list.append(item);
    });
    drop.append(list);
    if (m.note) drop.append(el("p", "muted", m.note));

    li.append(top, drop);
    menu.append(li);
    entries.push([li, top]);

    li.addEventListener("mouseenter", () => open(index));
    li.addEventListener("mouseleave", () => closeSoon());
    top.addEventListener("focus", () => open(index));
    top.addEventListener("click", () => open(index));
  });

  inner.append(logo, menu);
  header.append(inner);
  document.body.prepend(header);

  // ---------- 열고 닫기 (한 번에 하나만) ----------

  let closeTimer = null;

  function open(index) {
    clearTimeout(closeTimer);
    entries.forEach(([li, top], i) => {
      li.classList.toggle("open", i === index);
      top.setAttribute("aria-expanded", i === index ? "true" : "false");
    });
  }

  function close() {
    open(-1);
  }

  // 마우스가 메뉴 밖으로 나가면 잠깐 뒤에 닫는다 (메뉴 이름에서 펼친 상자로 옮겨 가는 사이에 닫히지 않게)
  function closeSoon() {
    clearTimeout(closeTimer);
    closeTimer = setTimeout(close, 200);
  }

  header.addEventListener("focusout", (event) => {
    if (!header.contains(event.relatedTarget)) close();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const opened = entries.find(([li]) => li.classList.contains("open"));
    if (opened) {
      close();
      opened[1].focus();
      close();   // focus 가 다시 펼치므로 한 번 더 닫는다
    }
  });
  document.addEventListener("click", (event) => {
    if (!header.contains(event.target)) close();
  });

  // ---------- 메뉴 항목 누르기 ----------

  menu.addEventListener("click", (event) => {
    const link = event.target.closest("a");
    if (!link) return;
    // [말로 물어보기]: 오른쪽 아래 채팅 창을 띄운다 (js/fab.js 가 처리)
    if (link.dataset.chat) {
      const fab = document.querySelector(".chat-fab");
      if (fab) {
        event.preventDefault();
        close();
        fab.click();
      }
      return;
    }
    // 같은 화면에서 # 뒤(찾는 낱말)만 바뀌면 브라우저가 화면을 다시 읽지 않으므로 직접 다시 연다
    const target = new URL(link.href);
    if (target.pathname === location.pathname && target.search === location.search && target.hash !== location.hash) {
      event.preventDefault();
      location.href = link.href;
      location.reload();
    }
  });
})();
