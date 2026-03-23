#!/usr/bin/env python3
"""Interactive setup wizard for selfcontrol-mcp."""

import json
import shutil
from pathlib import Path

import questionary
import yaml

from lib.config import REPO_DIR

CONFIG_PATH = REPO_DIR / "config.yaml"
EXAMPLE_START = REPO_DIR / "example.start.md"
START_MD = REPO_DIR / "start.md"
CLAUDE_SETTINGS = Path("~/.claude/settings.json").expanduser()
RESET_SCRIPT = REPO_DIR / "reset_generating.py"
NOTIFY_SCRIPT = REPO_DIR / "notify_user.py"
PERMISSION_SCRIPT = REPO_DIR / "permission_handler.py"
RATE_LIMIT_SCRIPT = REPO_DIR / "rate_limit_handler.py"


def setup_start_md() -> None:
    if START_MD.exists():
        overwrite = questionary.confirm(
            "start.md already exists. Overwrite with example?",
            default=False,
        ).ask()
        if not overwrite:
            return

    shutil.copy(EXAMPLE_START, START_MD)
    print(f"  Created {START_MD}")

    edit = questionary.confirm(
        "Open start.md in $EDITOR now?",
        default=False,
    ).ask()
    if edit:
        import os, subprocess
        editor = os.environ.get("EDITOR", "nano")
        subprocess.run([editor, str(START_MD)])


def setup_config() -> None:
    print("\n--- Config ---")

    defaults = {
        "default_prompt": "Continue working on the current task. If no task is active, review recent changes and suggest improvements.",
        "base_dir": "~/.ai-sessions",
        "check_interval_seconds": 10,
        "default_prompt_interval_minutes": 5,
        "generating_timeout_minutes": 30,
        "permission_timeout_minutes": 10,
        "permission_timeout_message": "Permission denied (timeout).",
    }

    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            existing = yaml.safe_load(f) or {}
        defaults.update(existing)

    default_prompt = questionary.text(
        "Default prompt (when queue & input are empty):",
        default=defaults["default_prompt"],
    ).ask()

    base_dir = questionary.text(
        "Session base directory:",
        default=defaults["base_dir"],
    ).ask()

    interval = questionary.text(
        "Scheduler check interval (seconds):",
        default=str(defaults["check_interval_seconds"]),
        validate=lambda v: v.isdigit() or "Must be a number",
    ).ask()

    default_prompt_interval = questionary.text(
        "Default prompt interval (minutes, min time between default prompts):",
        default=str(defaults["default_prompt_interval_minutes"]),
        validate=lambda v: v.isdigit() or "Must be a number",
    ).ask()

    timeout = questionary.text(
        "Generating lock timeout (minutes):",
        default=str(defaults["generating_timeout_minutes"]),
        validate=lambda v: v.isdigit() or "Must be a number",
    ).ask()

    perm_timeout = questionary.text(
        "Permission request timeout (minutes):",
        default=str(defaults["permission_timeout_minutes"]),
        validate=lambda v: v.isdigit() or "Must be a number",
    ).ask()

    perm_message = questionary.text(
        "Permission timeout message:",
        default=defaults["permission_timeout_message"],
    ).ask()

    config = {
        "default_prompt": default_prompt,
        "base_dir": base_dir,
        "check_interval_seconds": int(interval),
        "default_prompt_interval_minutes": int(default_prompt_interval),
        "generating_timeout_minutes": int(timeout),
        "permission_timeout_minutes": int(perm_timeout),
        "permission_timeout_message": perm_message,
    }

    # Preserve existing telegram config if present
    config["telegram_bot_token"] = defaults.get("telegram_bot_token", "")
    config["telegram_user_id"] = defaults.get("telegram_user_id", 0)

    with open(CONFIG_PATH, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    print(f"  Written {CONFIG_PATH}")


def setup_telegram() -> None:
    print("\n--- Telegram Bot ---")

    configure = questionary.confirm(
        "Configure Telegram bot?",
        default=True,
    ).ask()
    if not configure:
        return

    print()
    print("  To create a Telegram bot:")
    print("  1. Open Telegram and search for @BotFather")
    print("  2. Send /newbot and follow the instructions")
    print("  3. Copy the bot token (looks like: 123456:ABC-DEF...)")
    print()

    # Load existing config to get current values
    existing = {}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            existing = yaml.safe_load(f) or {}

    token = questionary.text(
        "Bot token:",
        default=existing.get("telegram_bot_token", ""),
        validate=lambda v: len(v) > 10 or "Enter a valid bot token",
    ).ask()

    print()
    print("  To find your Telegram user ID:")
    print("  1. Open Telegram and search for @userinfobot or @RawDataBot")
    print("  2. Send /start to the bot")
    print("  3. It will reply with your user ID (a number like 123456789)")
    print()

    user_id = questionary.text(
        "Your Telegram user ID:",
        default=str(existing.get("telegram_user_id", "")) if existing.get("telegram_user_id") else "",
        validate=lambda v: v.isdigit() or "Must be a number",
    ).ask()

    # Update config with telegram values
    existing["telegram_bot_token"] = token
    existing["telegram_user_id"] = int(user_id)

    with open(CONFIG_PATH, "w") as f:
        yaml.dump(existing, f, default_flow_style=False, sort_keys=False)

    print(f"  Telegram config saved to {CONFIG_PATH}")


def install_hook(settings: dict, event: str, script_path: str, check_name: str, matcher: str = "") -> bool:
    hooks = settings.setdefault("hooks", {})
    event_hooks = hooks.setdefault(event, [])

    for existing in event_hooks:
        for h in existing.get("hooks", []):
            if check_name in h.get("command", ""):
                print(f"  {event} hook already installed, skipping.")
                return False

    command = f"python3 {script_path}"
    event_hooks.append({
        "matcher": matcher,
        "hooks": [{"type": "command", "command": command}],
    })
    return True


def setup_hook() -> None:
    print("\n--- Claude Code Hooks ---")

    install = questionary.confirm(
        "Install hooks in ~/.claude/settings.json?",
        default=True,
    ).ask()
    if not install:
        return

    settings = {}
    if CLAUDE_SETTINGS.exists():
        with open(CLAUDE_SETTINGS) as f:
            settings = json.load(f)

    changed = False
    changed |= install_hook(settings, "Stop", str(RESET_SCRIPT.resolve()), "reset_generating.py")
    changed |= install_hook(settings, "Notification", str(NOTIFY_SCRIPT.resolve()), "notify_user.py")
    changed |= install_hook(settings, "PermissionRequest", str(PERMISSION_SCRIPT.resolve()), "permission_handler.py")
    changed |= install_hook(settings, "StopFailure", str(RATE_LIMIT_SCRIPT.resolve()), "rate_limit_handler.py", matcher="rate_limit")

    if changed:
        CLAUDE_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        with open(CLAUDE_SETTINGS, "w") as f:
            json.dump(settings, f, indent=2)
            f.write("\n")
        print(f"  Hooks installed in {CLAUDE_SETTINGS}")
    else:
        print("  All hooks already installed.")


def main() -> None:
    print("=== selfcontrol-mcp setup ===\n")

    setup_start_md()
    setup_config()
    setup_telegram()
    setup_hook()

    print("\n--- Done! ---")
    print("Next steps:")
    print("  1. Edit start.md to customize your startup prompt")
    print("  2. Start the scheduler:  python scheduler.py")
    print("  3. Start the Telegram bot:  python telebot_runner.py")
    print("  4. Configure the MCP server in Claude Code settings")


if __name__ == "__main__":
    main()
