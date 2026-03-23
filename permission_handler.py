#!/usr/bin/env python3
"""PermissionRequest hook — sends permission requests to Telegram for remote approval.

Each request gets a unique short ID to prevent stale responses from
accidentally approving unrelated future requests.
"""

import json
import logging
import sys
import time

from lib import Config, Session, TmuxClient, TelegramClient, SessionManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stderr,
)
log = logging.getLogger("permission_handler")

POLL_INTERVAL_SECONDS = 2


def respond(decision: str, message: str = "", suggestions: list | None = None) -> None:
    """Print the decision JSON to stdout and exit."""
    log.info("Responding: %s", decision)
    behavior = "allow" if decision == "always" else decision
    decision_obj: dict = {"behavior": behavior}
    if message and decision == "deny":
        decision_obj["message"] = message
    if decision == "always" and suggestions:
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
    # Read hook input
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

    config = Config()
    if not config.telegram_bot_token or not config.telegram_user_id:
        return

    pane_id = TmuxClient().get_pane_id_safe()
    session = Session(pane_id, config.base_dir)
    encoded = SessionManager.encode_name(pane_id)

    # Generate unique request ID
    req_id = Session.random_suffix(4)
    log.info("Permission request %s for tool=%s in session=%s", req_id, tool_name, pane_id)

    session.permissions_dir.mkdir(parents=True, exist_ok=True)

    # Format tool input for display
    input_preview = json.dumps(tool_input, indent=2, ensure_ascii=False)
    if len(input_preview) > 500:
        input_preview = input_preview[:500] + "\n..."

    # Build Telegram message with request-specific commands
    esc_enc = SessionManager.escape_markdown(encoded)
    esc_id = SessionManager.escape_markdown(req_id)
    commands = f"/{esc_enc}\\_allow\\_{esc_id} \u2014 Allow once\n"
    if has_always:
        commands += f"/{esc_enc}\\_always\\_{esc_id} \u2014 Always allow\n"
    commands += f"/{esc_enc}\\_deny\\_{esc_id} \u2014 Deny"

    message = (
        f"/{esc_enc}  Permission request `{req_id}`\n\n"
        f"Tool: `{tool_name}`\n"
        f"```\n{input_preview}\n```\n\n"
        f"{commands}"
    )

    telegram = TelegramClient(config.telegram_bot_token, config.telegram_user_id)
    msg_id = telegram.send_message(message, parse_mode="Markdown")
    if msg_id is None:
        log.error("Failed to send Telegram message")
        return
    log.info("Permission request sent (msg_id: %s)", msg_id)

    # Poll for response
    log.info("Polling for response (timeout: %d min)", config.permission_timeout_minutes)
    deadline = time.time() + config.permission_timeout_minutes * 60

    while time.time() < deadline:
        decision = session.read_permission_response(req_id)
        if decision:
            log.info("Got response: %s (id: %s)", decision, req_id)
            dots = {"allow": "\U0001f7e2", "always": "\U0001f535", "deny": "\U0001f7e0"}
            labels = {"allow": "Allowed (once)", "always": "Always allowed", "deny": "Denied"}
            telegram.edit_message(
                msg_id,
                f"{dots[decision]} /{esc_enc}  Permission request `{req_id}` \u2014 {labels[decision]}\n\n"
                f"Tool: `{tool_name}`\n```\n{input_preview}\n```",
                parse_mode="Markdown",
            )
            respond(decision, suggestions=suggestions if decision == "always" else None)
            return
        time.sleep(POLL_INTERVAL_SECONDS)

    # Timeout
    log.info("Timeout reached, denying")
    telegram.edit_message(
        msg_id,
        f"\U0001f534 /{esc_enc}  Permission request `{req_id}` \u2014 Timed out\n\n"
        f"Tool: `{tool_name}`\n```\n{input_preview}\n```\n\n"
        f"Request timed out after {config.permission_timeout_minutes} min. Permission denied.",
        parse_mode="Markdown",
    )
    respond("deny", config.permission_timeout_message)


if __name__ == "__main__":
    main()
