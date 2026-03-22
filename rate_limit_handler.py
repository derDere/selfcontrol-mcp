#!/usr/bin/env python3
"""StopFailure hook — detects rate limits, pauses the scheduler, and dismisses the dialog.

This hook fires when Claude Code's turn ends due to an API error.
Matcher: rate_limit

It writes ~/.ai-sessions/rate_limit.json so the scheduler stops sending prompts.
The user removes this file manually via /unlimit in Telegram.
After writing the file, it waits 1 second and sends Enter to dismiss the rate limit dialog.
"""

import json
import logging
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import telebot
import yaml

from session_mapper import encode_session_name, escape_for_markdown, get_pane_id

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stderr,
)
log = logging.getLogger("rate_limit_handler")

SCRIPT_DIR = Path(__file__).parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"


def main() -> None:
    hook_data = {}
    if not sys.stdin.isatty():
        try:
            hook_data = json.load(sys.stdin)
        except (json.JSONDecodeError, Exception):
            pass

    error = hook_data.get("error", "unknown")
    error_details = hook_data.get("error_details", "")

    log.info("StopFailure: error=%s details=%s", error, error_details)

    if not CONFIG_PATH.exists():
        return

    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f) or {}

    base_dir = Path(config.get("base_dir", "~/.ai-sessions")).expanduser()
    pane_id = get_pane_id()

    # Write rate limit marker file
    rate_limit_path = base_dir / "rate_limit.json"
    base_dir.mkdir(parents=True, exist_ok=True)
    # Send Telegram notification first to get message ID
    msg_id = None
    token = config.get("telegram_bot_token")
    user_id = config.get("telegram_user_id")
    if token and user_id:
        encoded = encode_session_name(pane_id)
        escaped = escape_for_markdown(encoded)
        message = (
            f"\U0001f534 /{escaped}  Rate limit reached\n\n"
            f"Session: `{pane_id}`\n"
            f"Error: {error_details or error}\n\n"
            f"Scheduler paused. Use /unlimit to resume."
        )
        try:
            bot = telebot.TeleBot(token)
            sent = bot.send_message(user_id, message, parse_mode="Markdown")
            msg_id = sent.message_id
            log.info("Telegram notification sent (msg_id: %s)", msg_id)
        except Exception as e:
            log.error("Failed to send Telegram message: %s", e)

    # Write rate limit marker file (includes Telegram msg_id for editing on unlimit)
    rate_limit_data = {
        "detected_at": datetime.now().isoformat(),
        "error": error,
        "error_details": error_details,
        "session": pane_id,
    }
    if msg_id:
        rate_limit_data["telegram_msg_id"] = msg_id
    rate_limit_path.write_text(json.dumps(rate_limit_data, indent=2) + "\n")
    log.info("Wrote rate limit file: %s", rate_limit_path)

    # Wait 1 second then send Enter to dismiss the rate limit dialog
    time.sleep(1)
    try:
        subprocess.run(
            ["tmux", "send-keys", "-t", pane_id, "Enter"],
            check=True, capture_output=True, text=True, timeout=5,
        )
        log.info("Sent Enter to %s to dismiss rate limit dialog", pane_id)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        log.error("Failed to send Enter to %s: %s", pane_id, e)


if __name__ == "__main__":
    main()
