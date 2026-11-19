"""텔레그램 봇에 웹훅 주소와 명령 목록을 등록한다 (배포 뒤 한 번 실행).

  python scripts/set_telegram_webhook.py              # .env 의 PUBLIC_BASE_URL 로 등록
  python scripts/set_telegram_webhook.py --url https://xxx.onrender.com
  python scripts/set_telegram_webhook.py --info       # 지금 등록된 상태 보기
  python scripts/set_telegram_webhook.py --delete     # 웹훅 지우기
  python scripts/set_telegram_webhook.py --new-secret # 비밀 문자열 새로 만들기 (화면에 한 번 보여 줌)

.env 에 TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET 이 있어야 한다. 토큰은 화면에 보여 주지 않는다.
Render 의 Environment 에도 같은 TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET 을 넣어야 서버가 받는다.
"""
import argparse
import secrets
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config  # noqa: E402

COMMANDS = [
    {"command": "start", "description": "처음 인사와 물어보는 방법"},
    {"command": "reset", "description": "처음부터 다시 하기"},
]


def call(method, payload=None):
    r = httpx.post(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/{method}", json=payload or {},
                   timeout=15)
    body = r.json()
    if not body.get("ok"):
        sys.exit(f"{method} 실패: {body.get('description')}")
    return body.get("result")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", help="배포 주소 (없으면 .env 의 PUBLIC_BASE_URL)")
    parser.add_argument("--info", action="store_true")
    parser.add_argument("--delete", action="store_true")
    parser.add_argument("--new-secret", action="store_true")
    args = parser.parse_args()

    if args.new_secret:
        print("아래 값을 .env 와 Render Environment 의 TELEGRAM_WEBHOOK_SECRET 에 넣으세요:")
        print(secrets.token_urlsafe(32))
        return
    if not config.TELEGRAM_BOT_TOKEN:
        sys.exit(".env 에 TELEGRAM_BOT_TOKEN 이 없습니다.")
    if args.info:
        info = call("getWebhookInfo")
        print("등록된 주소:", info.get("url") or "(없음)")
        print("밀린 메시지:", info.get("pending_update_count"))
        if info.get("last_error_message"):
            print("마지막 오류:", info["last_error_message"])
        return
    if args.delete:
        call("deleteWebhook")
        print("웹훅을 지웠습니다.")
        return

    base = (args.url or config.PUBLIC_BASE_URL).rstrip("/")
    if not base.startswith("https://"):
        sys.exit("배포 주소(https://...)를 --url 이나 .env 의 PUBLIC_BASE_URL 로 알려 주세요.")
    if not config.TELEGRAM_WEBHOOK_SECRET:
        sys.exit(".env 에 TELEGRAM_WEBHOOK_SECRET 이 없습니다. --new-secret 으로 만드세요.")
    call("setWebhook", {
        "url": f"{base}/api/telegram/webhook",
        "secret_token": config.TELEGRAM_WEBHOOK_SECRET,
        "allowed_updates": ["message", "callback_query"],
        "drop_pending_updates": True,
    })
    call("setMyCommands", {"commands": COMMANDS})
    bot = call("getMe")
    print(f"등록했습니다: {base}/api/telegram/webhook")
    print(f"텔레그램에서 @{bot['username']} 을 찾아 /start 를 보내 보세요.")


if __name__ == "__main__":
    main()
