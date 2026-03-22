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


def respond(decision: str, message: str = "", suggestions: list | None = None) -> None:
    """Print the decision JSON to stdout and exit."""
    log.info("Responding: %s", decision)
    behavior = "allow" if decision == "always" else decision
    decision_obj = {"behavior": behavior}
    if message and decision == "deny":
        decision_obj["message"] = message
    if decision == "always" and suggestions:
        # Pass through permission_suggestions so Claude Code persists the rule
        allow_suggestions = [s for s in suggestions if s.get("behavior") == "allow"]
        if allow_suggestions:
            decision_obj["updatedPermissions"] = allow_suggestions
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": decision_obj,
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

    # Response file unique to this request
    perm_dir = base_dir / pane_id / "permissions"
    perm_dir.mkdir(parents=True, exist_ok=True)
    resp_path = perm_dir / req_id

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
        sent = bot.send_message(user_id, message, parse_mode="Markdown")
        msg_id = sent.message_id
        log.info("Permission request sent to Telegram (msg_id: %s)", msg_id)
    except Exception as e:
        log.error("Failed to send Telegram message: %s", e)
        return

    # Poll for response file (filename IS the request ID, content is the decision)
    log.info("Polling for response at %s (timeout: %d min)", resp_path, timeout_minutes)
    deadline = time.time() + (timeout_minutes * 60)
    while time.time() < deadline:
        if resp_path.exists():
            try:
                decision = resp_path.read_text().strip()
                resp_path.unlink(missing_ok=True)
                if decision in ("allow", "always", "deny"):
                    log.info("Got response: %s (id: %s)", decision, req_id)
                    # Edit the Telegram message to show the decision
                    dots = {"allow": "\U0001f7e2", "always": "\U0001f535", "deny": "\U0001f7e0"}
                    labels = {"allow": "Allowed (once)", "always": "Always allowed", "deny": "Denied"}
                    done_msg = (
                        f"{dots[decision]} /{escaped_encoded}  Permission request `{req_id}` — {labels[decision]}\n\n"
                        f"Tool: `{tool_name}`\n"
                        f"```\n{input_preview}\n```"
                    )
                    try:
                        bot.edit_message_text(done_msg, chat_id=user_id, message_id=msg_id, parse_mode="Markdown")
                    except Exception:
                        pass
                    respond(decision, suggestions=suggestions if decision == "always" else None)
                    return
            except OSError as e:
                log.error("Error reading response file: %s", e)
        time.sleep(POLL_INTERVAL_SECONDS)

    # Timeout — edit the Telegram message to show it timed out
    log.info("Timeout reached, denying")
    timeout_msg = (
        f"\U0001f534 /{escaped_encoded}  Permission request `{req_id}` — Timed out\n\n"
        f"Tool: `{tool_name}`\n"
        f"```\n{input_preview}\n```\n\n"
        f"Request timed out after {timeout_minutes} min. Permission denied."
    )
    try:
        bot.edit_message_text(timeout_msg, chat_id=user_id, message_id=msg_id, parse_mode="Markdown")
    except Exception:
        pass

    respond("deny", timeout_message)


if __name__ == "__main__":
    main()
