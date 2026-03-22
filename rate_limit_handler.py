#!/usr/bin/env python3
"""StopFailure hook — detects rate limits, writes a shared wait file, and notifies via Telegram.

This hook fires when Claude Code's turn ends due to an API error.
Matcher: rate_limit

It writes ~/.ai-sessions/rate_limit.json so the scheduler knows to pause all sessions.
The reset time is parsed from the tmux pane content if possible, otherwise falls back
to a configurable default wait.
"""

import json
import logging
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import telebot
import yaml

from session_mapper import encode_session_name, get_pane_id

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stderr,
)
log = logging.getLogger("rate_limit_handler")

SCRIPT_DIR = Path(__file__).parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"

# Patterns to find reset time in tmux pane output (from claude-auto-retry and similar tools)
_RESET_PATTERNS = [
    re.compile(r"resets?\s+(?:at\s+)?(\d{1,2}(?::\d{2})?\s*(?:am|pm))", re.IGNORECASE),
    re.compile(r"try again in\s+(\d+)\s+(hour|minute|min)", re.IGNORECASE),
    re.compile(r"resets?\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm))\s*\(([^)]+)\)", re.IGNORECASE),
]


def parse_reset_time_from_text(text: str) -> datetime | None:
    """Try to extract a reset time from rate limit text shown in tmux."""
    for pattern in _RESET_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue

        groups = match.groups()

        # "try again in N hours/minutes"
        if len(groups) == 2 and groups[1].lower().startswith(("hour", "minute", "min")):
            amount = int(groups[0])
            if groups[1].lower().startswith("hour"):
                return datetime.now() + timedelta(hours=amount)
            else:
                return datetime.now() + timedelta(minutes=amount)

        # "resets at 3pm" or "resets 3:30pm"
        time_str = groups[0].strip()
        try:
            # Try "3pm" or "3:30pm"
            for fmt in ("%I:%M%p", "%I%p", "%I:%M %p", "%I %p"):
                try:
                    parsed = datetime.strptime(time_str.upper(), fmt)
                    now = datetime.now()
                    reset = now.replace(hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0)
                    if reset <= now:
                        reset += timedelta(days=1)
                    return reset
                except ValueError:
                    continue
        except Exception:
            continue

    return None


def capture_tmux_pane() -> str:
    """Capture the current tmux pane content to look for reset time info."""
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-p", "-S", "-30"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return ""


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
    default_wait = config.get("rate_limit_wait_minutes", 30)

    pane_id = get_pane_id()

    # Try to parse reset time from tmux pane content
    pane_text = capture_tmux_pane()
    reset_time = parse_reset_time_from_text(pane_text)

    if reset_time is None:
        # Also try parsing from error_details
        reset_time = parse_reset_time_from_text(error_details)

    if reset_time is None:
        reset_time = datetime.now() + timedelta(minutes=default_wait)
        log.info("Could not parse reset time, using default wait of %d minutes", default_wait)
    else:
        log.info("Parsed reset time: %s", reset_time.isoformat())

    # Write rate limit file next to all sessions (not inside a session)
    rate_limit_path = base_dir / "rate_limit.json"
    base_dir.mkdir(parents=True, exist_ok=True)
    rate_limit_data = {
        "detected_at": datetime.now().isoformat(),
        "reset_time": reset_time.isoformat(),
        "error": error,
        "error_details": error_details,
        "session": pane_id,
    }
    rate_limit_path.write_text(json.dumps(rate_limit_data, indent=2) + "\n")
    log.info("Wrote rate limit file: %s", rate_limit_path)

    # Send Telegram notification
    token = config.get("telegram_bot_token")
    user_id = config.get("telegram_user_id")
    if token and user_id:
        encoded = encode_session_name(pane_id)
        wait_minutes = int((reset_time - datetime.now()).total_seconds() / 60)
        message = (
            f"/{encoded}  Rate limit reached\n\n"
            f"Session: `{pane_id}`\n"
            f"Reset: {reset_time.strftime('%H:%M')} ({wait_minutes} min)\n"
            f"Error: {error_details or error}\n\n"
            f"Scheduler will pause and resume automatically."
        )
        try:
            bot = telebot.TeleBot(token)
            bot.send_message(user_id, message, parse_mode="Markdown")
            log.info("Telegram notification sent")
        except Exception as e:
            log.error("Failed to send Telegram message: %s", e)


if __name__ == "__main__":
    main()
