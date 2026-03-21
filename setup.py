#!/usr/bin/env python3
"""Interactive setup wizard for selfcontrol-mcp."""

import json
import shutil
from pathlib import Path

import questionary
import yaml

REPO_DIR = Path(__file__).parent
CONFIG_PATH = REPO_DIR / "config.yaml"
EXAMPLE_START = REPO_DIR / "example.start.md"
START_MD = REPO_DIR / "start.md"
CLAUDE_SETTINGS = Path("~/.claude/settings.json").expanduser()
RESET_SCRIPT = REPO_DIR / "reset_generating.py"


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
        "check_interval_seconds": 60,
        "generating_timeout_minutes": 30,
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

    timeout = questionary.text(
        "Generating lock timeout (minutes):",
        default=str(defaults["generating_timeout_minutes"]),
        validate=lambda v: v.isdigit() or "Must be a number",
    ).ask()

    config = {
        "default_prompt": default_prompt,
        "base_dir": base_dir,
        "check_interval_seconds": int(interval),
        "generating_timeout_minutes": int(timeout),
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


def setup_hook() -> None:
    print("\n--- Claude Code Hook ---")

    install = questionary.confirm(
        "Install the Stop hook in ~/.claude/settings.json?",
        default=True,
    ).ask()
    if not install:
        return

    command = f"python3 {RESET_SCRIPT.resolve()}"

    hook_entry = {
        "matcher": "",
        "hooks": [{"type": "command", "command": command}],
    }

    settings = {}
    if CLAUDE_SETTINGS.exists():
        with open(CLAUDE_SETTINGS) as f:
            settings = json.load(f)

    hooks = settings.setdefault("hooks", {})
    stop_hooks = hooks.setdefault("Stop", [])

    # Check if already installed
    for existing in stop_hooks:
        for h in existing.get("hooks", []):
            if "reset_generating.py" in h.get("command", ""):
                print("  Hook already installed, skipping.")
                return

    stop_hooks.append(hook_entry)

    CLAUDE_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    with open(CLAUDE_SETTINGS, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")

    print(f"  Hook installed in {CLAUDE_SETTINGS}")


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
