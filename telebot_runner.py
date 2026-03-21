#!/usr/bin/env python3
"""Telegram bot for selfcontrol-mcp user communication."""

import json
import logging
import random
import string
from datetime import datetime
from pathlib import Path

import telebot
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("telebot_runner")

SCRIPT_DIR = Path(__file__).parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f) or {}


config = load_config()
BASE_DIR = Path(config.get("base_dir", "~/.ai-sessions")).expanduser()
SESSION_MAP_PATH = BASE_DIR / "session_map.json"
BOT_TOKEN = config.get("telegram_bot_token", "")
AUTHORIZED_USER = config.get("telegram_user_id", 0)

if not BOT_TOKEN:
    raise SystemExit("Error: telegram_bot_token not set in config.yaml. Run setup.py first.")
if not AUTHORIZED_USER:
    raise SystemExit("Error: telegram_user_id not set in config.yaml. Run setup.py first.")

bot = telebot.TeleBot(BOT_TOKEN)
active_session: dict[int, str] = {}


# --- Session map ---

def encode_session_name(name: str) -> str:
    return "s_" + name.replace(":", "_").replace(".", "_")


def decode_session_command(cmd: str) -> str | None:
    session_map = load_session_map()
    return session_map.get(cmd)


def load_session_map() -> dict:
    if SESSION_MAP_PATH.exists():
        with open(SESSION_MAP_PATH) as f:
            return json.load(f)
    return {}


def save_session_map(mapping: dict) -> None:
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    with open(SESSION_MAP_PATH, "w") as f:
        json.dump(mapping, f, indent=2)
        f.write("\n")


def refresh_session_map() -> dict:
    mapping = {}
    if BASE_DIR.is_dir():
        for entry in sorted(BASE_DIR.iterdir()):
            if entry.is_dir() and entry.name != "__pycache__":
                encoded = encode_session_name(entry.name)
                mapping[encoded] = entry.name
    save_session_map(mapping)
    return mapping


def get_active_session(user_id: int) -> str | None:
    if user_id in active_session:
        return active_session[user_id]
    # Default to first session found
    mapping = refresh_session_map()
    if mapping:
        first = next(iter(mapping.values()))
        active_session[user_id] = first
        return first
    return None


# --- Auth check ---

def is_authorized(message) -> bool:
    if message.from_user.id != AUTHORIZED_USER:
        log.warning("Unauthorized access attempt — user_id=%s, username=%s",
                     message.from_user.id, message.from_user.username)
        return False
    return True


# --- File writing ---

def random_suffix(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def write_input_file(session_name: str, content: str) -> Path | None:
    input_dir = BASE_DIR / session_name / "input"
    if not input_dir.is_dir():
        log.warning("Input dir not found for session %s", session_name)
        return None
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    filename = f"{timestamp}_{random_suffix()}.txt"
    filepath = input_dir / filename
    filepath.write_text(content)
    return filepath


# --- Handlers ---

@bot.message_handler(commands=["start"])
def handle_start(message):
    if not is_authorized(message):
        return
    log.info("[/start] user_id=%s", message.from_user.id)
    session = get_active_session(message.from_user.id)
    session_text = f"Active session: `{session}`" if session else "No sessions found."
    bot.reply_to(
        message,
        f"selfcontrol-mcp Telegram bot\n\n{session_text}\n\n"
        "Use /sessions to list all sessions.\n"
        "Use /help for more commands.",
        parse_mode="Markdown",
    )


@bot.message_handler(commands=["help"])
def handle_help(message):
    if not is_authorized(message):
        return
    log.info("[/help] user_id=%s", message.from_user.id)
    bot.reply_to(
        message,
        "*Commands:*\n"
        "/start — Welcome & active session\n"
        "/current — Show current active session\n"
        "/sessions — List all sessions with switch commands\n"
        "/s\\_ENCODED — Switch to a session\n"
        "/unlock — Remove generating lock for active session\n"
        "/help — This message\n\n"
        "Any text message is sent to the active session as a prompt.",
        parse_mode="Markdown",
    )


@bot.message_handler(commands=["current"])
def handle_current(message):
    if not is_authorized(message):
        return
    session = get_active_session(message.from_user.id)
    log.info("[/current] user_id=%s, session=%s", message.from_user.id, session)
    if session:
        encoded = encode_session_name(session)
        escaped = encoded.replace("_", "\\_")
        bot.reply_to(message, f"Active session: `{session}`\nSwitch command: /{escaped}", parse_mode="Markdown")
    else:
        bot.reply_to(message, "No active session.")


@bot.message_handler(commands=["unlock"])
def handle_unlock(message):
    if not is_authorized(message):
        return
    session = get_active_session(message.from_user.id)
    if not session:
        bot.reply_to(message, "No active session.")
        return
    lock_path = BASE_DIR / session / "generating.lock"
    if lock_path.exists():
        lock_path.unlink()
        log.info("[/unlock] user_id=%s, session=%s — lock removed", message.from_user.id, session)
        bot.reply_to(message, f"Lock removed for `{session}`", parse_mode="Markdown")
    else:
        log.info("[/unlock] user_id=%s, session=%s — no lock found", message.from_user.id, session)
        bot.reply_to(message, f"No lock found for `{session}`", parse_mode="Markdown")


@bot.message_handler(commands=["sessions"])
def handle_sessions(message):
    if not is_authorized(message):
        return
    log.info("[/sessions] user_id=%s", message.from_user.id)
    mapping = refresh_session_map()
    if not mapping:
        bot.reply_to(message, "No sessions found in ~/.ai-sessions/")
        return

    current = get_active_session(message.from_user.id)
    lines = ["*Sessions:*\n"]
    for encoded, real_name in mapping.items():
        marker = " ← active" if real_name == current else ""
        escaped = encoded.replace("_", "\\_")
        lines.append(f"/{escaped} → `{real_name}`{marker}")

    bot.reply_to(message, "\n".join(lines), parse_mode="Markdown")


def write_permission_response(session_name: str, decision: str) -> bool:
    resp_path = BASE_DIR / session_name / "permission_response"
    try:
        resp_path.write_text(decision)
        return True
    except OSError:
        return False


@bot.message_handler(func=lambda m: m.text and m.text.endswith("_allow") and m.text.startswith("/s_"))
def handle_permission_allow(message):
    if not is_authorized(message):
        return
    cmd = message.text.strip().split()[0].lstrip("/")
    session_cmd = cmd.removesuffix("_allow")
    real_name = decode_session_command(session_cmd)
    if real_name and write_permission_response(real_name, "allow"):
        log.info("[permission] allow — user_id=%s, session=%s", message.from_user.id, real_name)
        bot.reply_to(message, f"Allowed (once) for `{real_name}`", parse_mode="Markdown")
    else:
        bot.reply_to(message, "Unknown session or write failed.")


@bot.message_handler(func=lambda m: m.text and m.text.endswith("_always") and m.text.startswith("/s_"))
def handle_permission_always(message):
    if not is_authorized(message):
        return
    cmd = message.text.strip().split()[0].lstrip("/")
    session_cmd = cmd.removesuffix("_always")
    real_name = decode_session_command(session_cmd)
    if real_name and write_permission_response(real_name, "always"):
        log.info("[permission] always — user_id=%s, session=%s", message.from_user.id, real_name)
        bot.reply_to(message, f"Always allowed for `{real_name}`", parse_mode="Markdown")
    else:
        bot.reply_to(message, "Unknown session or write failed.")


@bot.message_handler(func=lambda m: m.text and m.text.endswith("_deny") and m.text.startswith("/s_"))
def handle_permission_deny(message):
    if not is_authorized(message):
        return
    cmd = message.text.strip().split()[0].lstrip("/")
    session_cmd = cmd.removesuffix("_deny")
    real_name = decode_session_command(session_cmd)
    if real_name and write_permission_response(real_name, "deny"):
        log.info("[permission] deny — user_id=%s, session=%s", message.from_user.id, real_name)
        bot.reply_to(message, f"Denied for `{real_name}`", parse_mode="Markdown")
    else:
        bot.reply_to(message, "Unknown session or write failed.")


@bot.message_handler(func=lambda m: m.text and m.text.startswith("/s_"))
def handle_session_switch(message):
    if not is_authorized(message):
        return
    cmd = message.text.strip().split()[0].lstrip("/")
    real_name = decode_session_command(cmd)
    if real_name is None:
        # Refresh and retry
        refresh_session_map()
        real_name = decode_session_command(cmd)
    if real_name is None:
        bot.reply_to(message, f"Unknown session: `{cmd}`\nUse /sessions to see available sessions.", parse_mode="Markdown")
        return

    active_session[message.from_user.id] = real_name
    log.info("[switch] user_id=%s, session=%s", message.from_user.id, real_name)
    bot.reply_to(message, f"Switched to session: `{real_name}`", parse_mode="Markdown")


@bot.message_handler(content_types=["text"])
def handle_text(message):
    if not is_authorized(message):
        return
    session = get_active_session(message.from_user.id)
    if not session:
        bot.reply_to(message, "No active session. Start a tmux session with Claude Code first.")
        return

    filepath = write_input_file(session, message.text)
    if filepath:
        log.info("[text] user_id=%s, session=%s, file=%s, msg=%.80s",
                 message.from_user.id, session, filepath.name, message.text.replace("\n", " "))
        bot.reply_to(message, f"→ `{session}`", parse_mode="Markdown")
    else:
        log.error("[text] Failed to write — user_id=%s, session=%s", message.from_user.id, session)
        bot.reply_to(message, f"Failed to write to session `{session}`. Is it running?", parse_mode="Markdown")


@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    if not is_authorized(message):
        return
    session = get_active_session(message.from_user.id)
    if not session:
        bot.reply_to(message, "No active session.")
        return

    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded = bot.download_file(file_info.file_path)
    input_dir = BASE_DIR / session / "input"
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    photo_path = input_dir / f"{timestamp}_{random_suffix()}.jpg"
    photo_path.write_bytes(downloaded)

    caption = message.caption or "User sent a photo."
    text_path = write_input_file(session, f"{caption}\n\nPhoto saved: {photo_path}")
    if text_path:
        log.info("[photo] user_id=%s, session=%s, file=%s", message.from_user.id, session, photo_path.name)
        bot.reply_to(message, f"→ `{session}` (photo)", parse_mode="Markdown")


@bot.message_handler(content_types=["document"])
def handle_document(message):
    if not is_authorized(message):
        return
    session = get_active_session(message.from_user.id)
    if not session:
        bot.reply_to(message, "No active session.")
        return

    file_info = bot.get_file(message.document.file_id)
    downloaded = bot.download_file(file_info.file_path)
    input_dir = BASE_DIR / session / "input"
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    ext = Path(message.document.file_name).suffix if message.document.file_name else ""
    doc_path = input_dir / f"{timestamp}_{random_suffix()}{ext}"
    doc_path.write_bytes(downloaded)

    caption = message.caption or f"User sent a file: {message.document.file_name}"
    text_path = write_input_file(session, f"{caption}\n\nFile saved: {doc_path}")
    if text_path:
        log.info("[document] user_id=%s, session=%s, file=%s, original=%s",
                 message.from_user.id, session, doc_path.name, message.document.file_name)
        bot.reply_to(message, f"→ `{session}` (file)", parse_mode="Markdown")


def main() -> None:
    log.info("Telegram bot started — authorized user: %s", AUTHORIZED_USER)
    refresh_session_map()
    bot.infinity_polling()


if __name__ == "__main__":
    main()
