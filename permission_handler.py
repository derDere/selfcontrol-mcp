#!/usr/bin/env python3
"""PermissionRequest hook — sends permission requests to Telegram for remote approval.

This hook ONLY fires when Claude Code would normally show a permission dialog.
Tools that are already allowed never trigger this hook.

Each request gets a unique short ID to prevent stale responses from
accidentally approving unrelated future requests.
"""

import json
import logging
import random
import string
import sys
import time
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
log = logging.getLogger("permission_handler")

SCRIPT_DIR = Path(__file__).parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"
POLL_INTERVAL_SECONDS = 2


def random_id(length: int = 4) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def respond(decision: str) -> None:
    """Print the decision JSON to stdout and exit."""
    log.info("Responding: %s", decision)
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {
                "behavior": decision,
            },
        }
    }
    print(json.dumps(output), flush=True)


def main() -> None:
    # Read hook input from stdin
    hook_data = {}
    if not sys.stdin.isatty():
        try:
            hook_data = json.load(sys.stdin)
        except (json.JSONDecodeError, Exception):
            pass

    tool_name = hook_data.get("tool_name", "unknown")
    tool_input = hook_data.get("tool_input", {})
    suggestions = hook_data.get("permission_suggestions", [])
    has_always = len(suggestions) > 0

    if not CONFIG_PATH.exists():
        return

    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f) or {}

    token = config.get("telegram_bot_token")
    user_id = config.get("telegram_user_id")
    if not token or not user_id:
        return

    timeout_minutes = config.get("permission_timeout_minutes", 10)
    timeout_message = config.get("permission_timeout_message", "Permission denied (timeout).")
    base_dir = Path(config.get("base_dir", "~/.ai-sessions")).expanduser()

    pane_id = get_pane_id()
    encoded = encode_session_name(pane_id)

    # Generate unique request ID
    req_id = random_id()
    log.info("Permission request %s for tool=%s in session=%s", req_id, tool_name, pane_id)

    # Clean up any stale response file
    resp_path = base_dir / pane_id / "permission_response"
    resp_path.parent.mkdir(parents=True, exist_ok=True)
    if resp_path.exists():
        resp_path.unlink()

    # Format tool input for display
    input_preview = json.dumps(tool_input, indent=2, ensure_ascii=False)
    if len(input_preview) > 500:
        input_preview = input_preview[:500] + "\n..."

    # Build Telegram message with request-ID-specific commands
    escaped_encoded = escape_for_markdown(encoded)
    escaped_id = escape_for_markdown(req_id)
    commands = (
        f"/{escaped_encoded}\\_allow\\_{escaped_id} — Allow once\n"
    )
    if has_always:
        commands += f"/{escaped_encoded}\\_always\\_{escaped_id} — Always allow\n"
    commands += f"/{escaped_encoded}\\_deny\\_{escaped_id} — Deny"

    message = (
        f"/{escaped_encoded}  Permission request `{req_id}`\n\n"
        f"Tool: `{tool_name}`\n"
        f"```\n{input_preview}\n```\n\n"
        f"{commands}"
    )

    try:
        bot = telebot.TeleBot(token)
        bot.send_message(user_id, message, parse_mode="Markdown")
        log.info("Permission request sent to Telegram")
    except Exception as e:
        log.error("Failed to send Telegram message: %s", e)
        return

    # Poll for response (file content must match our request ID)
    log.info("Polling for response at %s (timeout: %d min, id: %s)", resp_path, timeout_minutes, req_id)
    deadline = time.time() + (timeout_minutes * 60)
    while time.time() < deadline:
        if resp_path.exists():
            try:
                content = resp_path.read_text().strip()
                # Expected format: "allow:req_id" or "deny:req_id"
                if ":" in content:
                    decision, resp_id = content.split(":", 1)
                    if resp_id == req_id and decision in ("allow", "always", "deny"):
                        resp_path.unlink(missing_ok=True)
                        log.info("Got matching response: %s (id: %s)", decision, resp_id)
                        respond("allow" if decision in ("allow", "always") else "deny")
                        return
                    else:
                        resp_path.unlink(missing_ok=True)
                        log.warning("Stale/mismatched response: %s (expected id: %s)", content, req_id)
                else:
                    resp_path.unlink(missing_ok=True)
                    log.warning("Invalid response format: %s", content)
            except OSError as e:
                log.error("Error reading response file: %s", e)
        time.sleep(POLL_INTERVAL_SECONDS)

    # Timeout — notify and deny
    log.info("Timeout reached, denying")
    try:
        bot = telebot.TeleBot(token)
        bot.send_message(user_id, f"/{escaped_encoded}  {timeout_message}")
    except Exception:
        pass

    respond("deny")


if __name__ == "__main__":
    main()
