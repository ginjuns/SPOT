"""디스코드 봇의 슬래시 명령을 등록하고 초대 링크를 보여 준다 (한 번 실행).

  python scripts/register_discord_commands.py          # 명령 등록 + 초대 링크
  python scripts/register_discord_commands.py --list   # 등록된 명령 보기

.env 에 DISCORD_APPLICATION_ID, DISCORD_BOT_TOKEN 이 있어야 한다. 토큰은 화면에 보여 주지 않는다.
등록한 뒤 Developer Portal → General Information → Interactions Endpoint URL 에
https://<배포 주소>/api/discord/interactions 를 넣는다 (넣는 순간 디스코드가 서명 검사를 시험한다).
"""
import argparse
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config  # noqa: E402
from app.routers import discord  # noqa: E402

CONTEXTS = [0, 1]   # 0 = 서버 채널, 1 = 봇과의 개인 대화
COMMANDS = [
    {"name": discord.ASK_COMMAND, "type": 1, "contexts": CONTEXTS,
     "description": "지금 상황을 적으면 확인해 볼 만한 나라·지자체 지원을 찾아 드려요",
     "options": [{"name": discord.QUESTION_OPTION, "type": 3, "required": True, "max_length": 300,
                  "description": "예: 허리가 아파서 병원비 지원이 있나요?"}]},
    {"name": discord.RESET_COMMAND, "type": 1, "contexts": CONTEXTS,
     "description": "앞에서 고른 나이대와 지역을 지우고 처음부터 다시 해요"},
    {"name": discord.HELP_COMMAND, "type": 1, "contexts": CONTEXTS,
     "description": "물어보는 방법과 예시 질문을 보여 드려요"},
]


def call(method, path, payload=None):
    r = httpx.request(method, f"{discord.API}{path}", json=payload, timeout=15, headers={
        "Authorization": f"Bot {config.DISCORD_BOT_TOKEN}",
        "User-Agent": "DiscordBot (https://github.com, 1.0)",
    })
    if r.status_code >= 300:
        sys.exit(f"{method} {path} 실패 ({r.status_code}): {r.text[:500]}")
    return r.json()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    if not (config.DISCORD_APPLICATION_ID and config.DISCORD_BOT_TOKEN):
        sys.exit(".env 에 DISCORD_APPLICATION_ID, DISCORD_BOT_TOKEN 이 없습니다.")
    path = f"/applications/{config.DISCORD_APPLICATION_ID}/commands"
    if not args.list:
        call("PUT", path, COMMANDS)   # 목록 전체를 이것으로 바꾼다
        print("명령을 등록했습니다.")
    for c in call("GET", path):
        print(f"  /{c['name']} — {c['description']}")
    print("\n봇 초대 링크 (서버 관리자가 열어서 서버에 추가):")
    print(f"https://discord.com/oauth2/authorize?client_id={config.DISCORD_APPLICATION_ID}"
          "&scope=applications.commands+bot&permissions=0")


if __name__ == "__main__":
    main()
