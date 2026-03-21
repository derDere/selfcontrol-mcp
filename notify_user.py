#!/usr/bin/env python3
"""Sends a Telegram notification when Claude Code needs user attention."""

import json
import sys
from pathlib import Path

import telebot
import yaml

SCRIPT_DIR = Path(__file__).parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"


from session_mapper import encode_session_name, get_pane_id


def main() -> None:
    if not CONFIG_PATH.exists():
        return

    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f) or {}

    token = config.get("telegram_bot_token")
    user_id = config.get("telegram_user_id")
    if not token or not user_id:
        return

    pane_id = get_pane_id()
    encoded = encode_session_name(pane_id)

    # Read hook input from stdin if available
    detail = ""
    if not sys.stdin.isatty():
        try:
            hook_data = json.load(sys.stdin)
            detail = hook_data.get("message", "")
        except (json.JSONDecodeError, Exception):
            pass

    message = f"/{encoded}  Needs attention\n\n"
    if detail:
        message += detail
    else:
        message += "Claude Code is waiting for approval or input."

    try:
        bot = telebot.TeleBot(token)
        bot.send_message(user_id, message)
    except Exception:
        pass


if __name__ == "__main__":
    main()
