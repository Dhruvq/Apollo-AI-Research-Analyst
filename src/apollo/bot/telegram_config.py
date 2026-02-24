"""
Apollo Telegram Bot — Setup Verification Helper
================================================
Run this ONCE to verify your Telegram environment is correctly configured.

Prerequisites:
  1. Create a Telegram bot via @BotFather → copy the token → TELEGRAM_BOT_TOKEN in .env
  2. Create a public Telegram supergroup → add bot as Admin
  3. Get the supergroup chat_id (add @userinfobot to the group — it returns a negative integer)
  4. Add TELEGRAM_CHAT_ID to .env
  5. Run: python bot/telegram_config.py

The bot itself is started with:
    python bot/telegram_bot.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv()


def check_env_vars() -> bool:
    ok = True
    for var in ("GOOGLE_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        val = os.environ.get(var)
        if val:
            preview = val[:8] + "..." if len(val) > 8 else val
            print(f"  [ok] {var} = {preview}")
        else:
            print(f"  [MISSING] {var} — add to .env")
            ok = False
    return ok


def verify_bot_token() -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        return False
    try:
        url = f"https://api.telegram.org/bot{token}/getMe"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
        if data.get("ok"):
            bot = data["result"]
            print(f"  [ok] Bot verified: @{bot['username']} (id={bot['id']})")
            return True
        print(f"  [FAIL] Telegram API error: {data}")
        return False
    except Exception as e:
        print(f"  [FAIL] Could not reach Telegram API: {e}")
        return False


def send_test_message() -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False
    payload = json.dumps({
        "chat_id": chat_id,
        "text": "Apollo bot is configured and ready.",
    }).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        if data.get("ok"):
            print(f"  [ok] Test message sent to chat {chat_id}")
            return True
        print(f"  [FAIL] sendMessage error: {data.get('description')}")
        return False
    except Exception as e:
        print(f"  [FAIL] sendMessage failed: {e}")
        return False


def print_next_steps() -> None:
    print("""
╔══════════════════════════════════════════════════════════════════╗
║  Apollo Telegram Bot — How to Run                                ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  Start the bot:                                                  ║
║    python bot/telegram_bot.py                                    ║
║                                                                  ║
║  Keep it running persistently (macOS):                           ║
║    nohup python bot/telegram_bot.py >> logs/bot.log 2>&1 &       ║
║                                                                  ║
║  Bot behaviour in Telegram:                                      ║
║    - Responds to @ApolloAIResearchBot mentions in the group      ║
║    - Also responds to direct messages                            ║
║    - 10 questions/day global rate limit (resets at midnight)     ║
║    - Answers only from papers stored in ZeroClaw memory          ║
║    - 3 paragraphs max per reply, arXiv links included            ║
║    - Empty memory → "No relevant research found."                ║
║                                                                  ║
║  To populate memory, run the full pipeline:                      ║
║    python run_biweekly.py                                        ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
""")


if __name__ == "__main__":
    print("Apollo Telegram Bot — Setup Verification\n")

    print("Environment variables:")
    env_ok = check_env_vars()

    print("\nBot token:")
    token_ok = verify_bot_token()

    if env_ok and token_ok:
        print("\nTest message:")
        send_test_message()

    print_next_steps()

    if not env_ok or not token_ok:
        sys.exit(1)

    print("[setup] All checks passed. Run: python bot/telegram_bot.py")
