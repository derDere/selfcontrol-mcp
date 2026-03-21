#!/usr/bin/env python3
"""PermissionRequest hook — sends permission requests to Telegram for remote approval."""

import json
import sys
import time
import subprocess
from pathlib import Path

import telebot
import yaml

SCRIPT_DIR = Path(__file__).parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"
POLL_INTERVAL_SECONDS = 2


def get_pane_id() -> str:
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#{session_name}:#{window_index}.#{pane_index}"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return "unknown"


def encode_session_name(name: str) -> str:
    return "s_" + name.replace(":", "_").replace(".", "_")


def response_file_path(base_dir: Path, pane_id: str) -> Path:
    return base_dir / pane_id / "permission_response"


def main() -> None:
    if not CONFIG_PATH.exists():
        # No config — deny by default
        print(json.dumps({"decision": "deny"}))
        return

    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f) or {}

    token = config.get("telegram_bot_token")
    user_id = config.get("telegram_user_id")
    if not token or not user_id:
        print(json.dumps({"decision": "deny"}))
        return

    timeout_minutes = config.get("permission_timeout_minutes", 10)
    timeout_message = config.get("permission_timeout_message", "Permission denied (timeout).")
    base_dir = Path(config.get("base_dir", "~/.ai-sessions")).expanduser()

    # Read hook input from stdin
    hook_data = {}
    if not sys.stdin.isatty():
        try:
            hook_data = json.load(sys.stdin)
        except (json.JSONDecodeError, Exception):
            pass

    tool_name = hook_data.get("tool_name", "unknown")
    tool_input = hook_data.get("tool_input", {})

    pane_id = get_pane_id()
    encoded = encode_session_name(pane_id)

    # Clean up any stale response file
    resp_path = response_file_path(base_dir, pane_id)
    resp_path.parent.mkdir(parents=True, exist_ok=True)
    if resp_path.exists():
        resp_path.unlink()

    # Format tool input for display
    input_preview = json.dumps(tool_input, indent=2, ensure_ascii=False)
    if len(input_preview) > 500:
        input_preview = input_preview[:500] + "\n..."

    # Send permission request to Telegram
    escaped_encoded = encoded.replace("_", "\\_")
    message = (
        f"/{escaped_encoded}  Permission request\n\n"
        f"Tool: `{tool_name}`\n"
        f"```\n{input_preview}\n```\n\n"
        f"/{encoded}\\_allow — Allow once\n"
        f"/{encoded}\\_always — Always allow\n"
        f"/{encoded}\\_deny — Deny"
    )

    try:
        bot = telebot.TeleBot(token)
        bot.send_message(user_id, message, parse_mode="Markdown")
    except Exception:
        # If we can't send the message, deny
        print(json.dumps({"decision": "deny"}))
        return

    # Poll for response
    deadline = time.time() + (timeout_minutes * 60)
    while time.time() < deadline:
        if resp_path.exists():
            try:
                decision = resp_path.read_text().strip()
                resp_path.unlink(missing_ok=True)
                if decision in ("allow", "always", "deny"):
                    print(json.dumps({"decision": decision}))
                    return
            except OSError:
                pass
        time.sleep(POLL_INTERVAL_SECONDS)

    # Timeout — notify and deny
    try:
        bot = telebot.TeleBot(token)
        bot.send_message(user_id, f"/{escaped_encoded}  {timeout_message}")
    except Exception:
        pass

    print(json.dumps({"decision": "deny"}))


if __name__ == "__main__":
    main()
