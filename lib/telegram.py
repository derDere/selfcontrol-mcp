"""Telegram bot wrapper for one-shot message sending."""

import telebot


class TelegramClient:
    """Thin wrapper around pyTelegramBotAPI for sending messages to a single user."""

    def __init__(self, token: str, user_id: int):
        self.bot = telebot.TeleBot(token)
        self.user_id = user_id

    def send_message(self, text: str, parse_mode: str | None = None) -> int | None:
        """Send a text message. Returns the message_id or None on failure."""
        try:
            sent = self.bot.send_message(self.user_id, text, parse_mode=parse_mode)
            return sent.message_id
        except Exception:
            return None

    def send_photo(self, photo, caption: str = "", parse_mode: str | None = None) -> int | None:
        try:
            sent = self.bot.send_photo(self.user_id, photo, caption=caption, parse_mode=parse_mode)
            return sent.message_id
        except Exception:
            return None

    def send_document(self, doc, caption: str = "", parse_mode: str | None = None) -> int | None:
        try:
            sent = self.bot.send_document(self.user_id, doc, caption=caption, parse_mode=parse_mode)
            return sent.message_id
        except Exception:
            return None

    def edit_message(self, msg_id: int, text: str, parse_mode: str | None = None) -> bool:
        try:
            self.bot.edit_message_text(text, chat_id=self.user_id, message_id=msg_id, parse_mode=parse_mode)
            return True
        except Exception:
            return False
