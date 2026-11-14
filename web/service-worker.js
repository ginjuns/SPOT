// SPOT 서비스 워커: 화면 파일(HTML·CSS·JS·아이콘)만 캐시한다. API 응답은 캐시하지 않는다.
// 화면 파일을 고쳐서 다시 배포할 때는 아래 버전 숫자를 올린다 (옛 캐시가 지워진다).
const CACHE = "spot-v1";

const SCREEN_FILES = [
  "./",
  "index.html",
  "chat.html",
  "search.html",
  "policy.html",
  "share.html",
  "css/style.css",
  "js/settings.js",
  "js/api.js",
  "js/chat.js",
  "js/search.js",
  "js/policy.js",
  "js/share.js",
  "manifest.webmanifest",
  "icons/icon-192.png",
  "icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SCREEN_FILES)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  // 이름이 다른 옛 캐시는 지운다
  event.waitUntil(
    caches.keys()
      .then((names) => Promise.all(names.filter((n) => n !== CACHE).map((n) => caches.delete(n))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  // API, 다른 사이트, GET 이 아닌 요청은 건드리지 않는다 (항상 서버로 간다).
  if (request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/")) return;

  // 네트워크 먼저 → 실패하면 캐시. 캐시 먼저로 하면 다시 배포해도 옛 화면이 계속 남는다.
  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(request, copy));
        }
        return response;
      })
      .catch(() =>
        // 주소 뒤의 ?id=... 같은 값은 무시하고 화면 파일을 찾는다
        caches.match(request, { ignoreSearch: true }).then((cached) => cached || Response.error())
      )
  );
});
