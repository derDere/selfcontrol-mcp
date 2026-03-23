#!/usr/bin/env python3
"""Notification hook — sends a Telegram message when Claude Code needs user attention."""

import json
import sys

from lib import Config, TmuxClient, TelegramClient, SessionManager


def main() -> None:
    config = Config()
    if not config.telegram_bot_token or not config.telegram_user_id:
        return

    pane_id = TmuxClient().get_pane_id_safe()
    encoded = SessionManager.encode_name(pane_id)

    # Read hook input from stdin
    detail = ""
    if not sys.stdin.isatty():
        try:
            hook_data = json.load(sys.stdin)
            detail = hook_data.get("message", "")
        except (json.JSONDecodeError, Exception):
            pass

    # Skip permission-related notifications (handled by permission_handler.py)
    if any(w in detail.lower() for w in ("permission", "approval", "approve", "waiting")):
        return

    message = f"/{encoded}  Needs attention\n\n"
    message += detail or "Claude Code is waiting for approval or input."

    TelegramClient(config.telegram_bot_token, config.telegram_user_id).send_message(message)


if __name__ == "__main__":
    main()
