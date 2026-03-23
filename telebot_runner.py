#!/usr/bin/env python3
"""Telegram bot for selfcontrol-mcp user communication."""

import logging
import re
from datetime import datetime
from pathlib import Path

import telebot

from lib import Config, Session, SessionManager, RateLimiter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("telebot_runner")


class TelebotRunner:
    PERM_RE = re.compile(r"^s_(.+)_(allow|always|deny)_([a-z0-9]+)$")

    def __init__(self, config: Config):
        self.config = config
        self.sessions = SessionManager(config.base_dir)
        self.rate_limiter = RateLimiter(config.base_dir)
        self.bot = telebot.TeleBot(config.telegram_bot_token)
        self.authorized_user = config.telegram_user_id
        self.active_session: dict[int, str] = {}
        self._register_handlers()

    def _is_authorized(self, message) -> bool:
        if message.from_user.id != self.authorized_user:
            log.warning("Unauthorized access attempt — user_id=%s, username=%s",
                        message.from_user.id, message.from_user.username)
            return False
        return True

    def _get_active_session(self, user_id: int) -> str | None:
        if user_id in self.active_session:
            return self.active_session[user_id]
        mapping = self.sessions.refresh_map()
        if mapping:
            first = next(iter(mapping.values()))
            self.active_session[user_id] = first
            return first
        return None

    def _register_handlers(self):
        bot = self.bot
        encode = SessionManager.encode_name
        escape = SessionManager.escape_markdown

        @bot.message_handler(commands=["start"])
        def handle_start(message):
            if not self._is_authorized(message):
                return
            session = self._get_active_session(message.from_user.id)
            session_text = f"Active session: `{session}`" if session else "No sessions found."
            bot.reply_to(
                message,
                f"selfcontrol-mcp Telegram bot\n\n{session_text}\n\n"
                "Use /sessions to list all sessions.\nUse /help for more commands.",
                parse_mode="Markdown",
            )

        @bot.message_handler(commands=["help"])
        def handle_help(message):
            if not self._is_authorized(message):
                return
            bot.reply_to(
                message,
                "*Commands:*\n"
                "/start — Welcome & active session\n"
                "/current — Show current active session\n"
                "/sessions — List all sessions with switch commands\n"
                "/s\\_ENCODED — Switch to a session\n"
                "/unlock — Remove generating lock for active session\n"
                "/unlimit — Remove rate limit pause and resume scheduler\n"
                "/help — This message\n\n"
                "Any text message is sent to the active session as a prompt.",
                parse_mode="Markdown",
            )

        @bot.message_handler(commands=["current"])
        def handle_current(message):
            if not self._is_authorized(message):
                return
            name = self._get_active_session(message.from_user.id)
            if name:
                bot.reply_to(message,
                             f"Active session: `{name}`\nSwitch command: /{escape(encode(name))}",
                             parse_mode="Markdown")
            else:
                bot.reply_to(message, "No active session.")

        @bot.message_handler(commands=["unlock"])
        def handle_unlock(message):
            if not self._is_authorized(message):
                return
            name = self._get_active_session(message.from_user.id)
            if not name:
                bot.reply_to(message, "No active session.")
                return
            session = self.sessions.get_session(name)
            if session.clear_lock():
                log.info("[/unlock] session=%s — lock removed", name)
                bot.reply_to(message, f"Lock removed for `{name}`", parse_mode="Markdown")
            else:
                log.info("[/unlock] session=%s — no lock found", name)
                bot.reply_to(message, f"No lock found for `{name}`", parse_mode="Markdown")

        @bot.message_handler(commands=["unlimit"])
        def handle_unlimit(message):
            if not self._is_authorized(message):
                return
            data = self.rate_limiter.load()
            if data:
                msg_id = data.get("telegram_msg_id")
                session_name = data.get("session", "unknown")
                error_details = data.get("error_details") or data.get("error", "")
                if msg_id:
                    try:
                        bot.edit_message_text(
                            f"\U0001f7e2 Rate limit lifted\n\n"
                            f"Session: `{session_name}`\n"
                            f"Error: {error_details}\n\nResumed by /unlimit",
                            chat_id=message.chat.id, message_id=msg_id, parse_mode="Markdown",
                        )
                    except Exception:
                        pass
                self.rate_limiter.clear()
                log.info("[/unlimit] rate limit file removed")
                bot.reply_to(message, "Rate limit removed. Scheduler will resume.")
            else:
                bot.reply_to(message, "No rate limit active.")

        @bot.message_handler(commands=["sessions"])
        def handle_sessions(message):
            if not self._is_authorized(message):
                return
            mapping = self.sessions.refresh_map()
            if not mapping:
                bot.reply_to(message, "No sessions found in ~/.ai-sessions/")
                return
            current = self._get_active_session(message.from_user.id)
            lines = ["*Sessions:*\n"]
            for encoded, real_name in mapping.items():
                marker = " \u2190 active" if real_name == current else ""
                lines.append(f"/{escape(encoded)} \u2192 `{real_name}`{marker}")
            bot.reply_to(message, "\n".join(lines), parse_mode="Markdown")

        @bot.message_handler(func=lambda m: m.text and m.text.startswith("/s_")
                             and self.PERM_RE.search(m.text.strip().split()[0].lstrip("/")))
        def handle_permission_response(message):
            if not self._is_authorized(message):
                return
            cmd = message.text.strip().split()[0].lstrip("/")
            match = self.PERM_RE.match(cmd)
            if not match:
                bot.reply_to(message, "Invalid permission command format.")
                return
            session_part, decision, req_id = match.groups()
            session_cmd = f"s_{session_part}"
            real_name = self.sessions.decode_command(session_cmd)
            if not real_name:
                self.sessions.refresh_map()
                real_name = self.sessions.decode_command(session_cmd)
            if real_name:
                session = self.sessions.get_session(real_name)
                if session.write_permission_response(req_id, decision):
                    labels = {"allow": "Allowed (once)", "always": "Always allowed", "deny": "Denied"}
                    log.info("[permission] %s — session=%s, req_id=%s", decision, real_name, req_id)
                    bot.reply_to(message, f"{labels[decision]} for `{real_name}` (req: {req_id})",
                                 parse_mode="Markdown")
                    return
            bot.reply_to(message, "Unknown session or write failed.")

        @bot.message_handler(func=lambda m: m.text and m.text.startswith("/s_"))
        def handle_session_switch(message):
            if not self._is_authorized(message):
                return
            cmd = message.text.strip().split()[0].lstrip("/")
            real_name = self.sessions.decode_command(cmd)
            if real_name is None:
                self.sessions.refresh_map()
                real_name = self.sessions.decode_command(cmd)
            if real_name is None:
                bot.reply_to(message, f"Unknown session: `{cmd}`\nUse /sessions to see available sessions.",
                             parse_mode="Markdown")
                return
            self.active_session[message.from_user.id] = real_name
            log.info("[switch] session=%s", real_name)
            bot.reply_to(message, f"Switched to session: `{real_name}`", parse_mode="Markdown")

        @bot.message_handler(content_types=["text"])
        def handle_text(message):
            if not self._is_authorized(message):
                return
            name = self._get_active_session(message.from_user.id)
            if not name:
                bot.reply_to(message, "No active session. Start a tmux session with Claude Code first.")
                return
            session = self.sessions.get_session(name)
            filepath = session.write_input_file(message.text)
            if filepath:
                log.info("[text] session=%s, file=%s, msg=%.80s",
                         name, filepath.name, message.text.replace("\n", " "))
                bot.reply_to(message, f"\u2192 `{name}`", parse_mode="Markdown")
            else:
                bot.reply_to(message, f"Failed to write to session `{name}`. Is it running?",
                             parse_mode="Markdown")

        @bot.message_handler(content_types=["photo"])
        def handle_photo(message):
            if not self._is_authorized(message):
                return
            name = self._get_active_session(message.from_user.id)
            if not name:
                bot.reply_to(message, "No active session.")
                return
            session = self.sessions.get_session(name)
            file_info = bot.get_file(message.photo[-1].file_id)
            downloaded = bot.download_file(file_info.file_path)
            ts = datetime.now().strftime(Session.TIMESTAMP_FORMAT)
            photo_path = session.input_dir / f"{ts}_{Session.random_suffix()}.jpg"
            photo_path.write_bytes(downloaded)
            caption = message.caption or "User sent a photo."
            session.write_input_file(f"{caption}\n\nPhoto saved: {photo_path}")
            log.info("[photo] session=%s, file=%s", name, photo_path.name)
            bot.reply_to(message, f"\u2192 `{name}` (photo)", parse_mode="Markdown")

        @bot.message_handler(content_types=["document"])
        def handle_document(message):
            if not self._is_authorized(message):
                return
            name = self._get_active_session(message.from_user.id)
            if not name:
                bot.reply_to(message, "No active session.")
                return
            session = self.sessions.get_session(name)
            file_info = bot.get_file(message.document.file_id)
            downloaded = bot.download_file(file_info.file_path)
            ts = datetime.now().strftime(Session.TIMESTAMP_FORMAT)
            ext = Path(message.document.file_name).suffix if message.document.file_name else ""
            doc_path = session.input_dir / f"{ts}_{Session.random_suffix()}{ext}"
            doc_path.write_bytes(downloaded)
            caption = message.caption or f"User sent a file: {message.document.file_name}"
            session.write_input_file(f"{caption}\n\nFile saved: {doc_path}")
            log.info("[document] session=%s, file=%s, original=%s",
                     name, doc_path.name, message.document.file_name)
            bot.reply_to(message, f"\u2192 `{name}` (file)", parse_mode="Markdown")

    def run(self) -> None:
        log.info("Telegram bot started — authorized user: %s", self.authorized_user)
        self.sessions.refresh_map()
        self.bot.infinity_polling()


if __name__ == "__main__":
    cfg = Config()
    if not cfg.telegram_bot_token:
        raise SystemExit("Error: telegram_bot_token not set in config.yaml. Run setup.py first.")
    if not cfg.telegram_user_id:
        raise SystemExit("Error: telegram_user_id not set in config.yaml. Run setup.py first.")
    TelebotRunner(cfg).run()
