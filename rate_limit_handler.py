#!/usr/bin/env python3
"""StopFailure hook — detects rate limits, pauses the scheduler, and dismisses the dialog.

Matcher: rate_limit
Writes ~/.ai-sessions/rate_limit.json so the scheduler stops sending prompts.
The user removes this file via /unlimit in Telegram.
"""

import json
import logging
import sys
import time

from lib import Config, TmuxClient, TelegramClient, SessionManager, RateLimiter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stderr,
)
log = logging.getLogger("rate_limit_handler")


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

    config = Config()
    tmux = TmuxClient()
    pane_id = tmux.get_pane_id_safe()
    rate_limiter = RateLimiter(config.base_dir)

    # Send Telegram notification first to capture msg_id
    msg_id = None
    if config.telegram_bot_token and config.telegram_user_id:
        encoded = SessionManager.encode_name(pane_id)
        escaped = SessionManager.escape_markdown(encoded)
        message = (
            f"\U0001f534 /{escaped}  Rate limit reached\n\n"
            f"Session: `{pane_id}`\n"
            f"Error: {error_details or error}\n\n"
            f"Scheduler paused. Use /unlimit to resume."
        )
        telegram = TelegramClient(config.telegram_bot_token, config.telegram_user_id)
        msg_id = telegram.send_message(message, parse_mode="Markdown")
        if msg_id:
            log.info("Telegram notification sent (msg_id: %s)", msg_id)
        else:
            log.error("Failed to send Telegram message")

    rate_limiter.set_limit(error, error_details, pane_id, msg_id)
    log.info("Wrote rate limit file: %s", rate_limiter.path)

    # Dismiss the rate limit dialog
    time.sleep(1)
    if tmux.send_enter(pane_id):
        log.info("Sent Enter to %s to dismiss rate limit dialog", pane_id)
    else:
        log.error("Failed to send Enter to %s", pane_id)


if __name__ == "__main__":
    main()
