"""FastMCP server exposing prompt_now, prompt_later, message_user tools."""

import re
from datetime import datetime, timedelta
from pathlib import Path

from fastmcp import FastMCP

from lib import Config, Session, SessionManager, TmuxClient, TelegramClient, NotInTmuxError

config = Config()

if not config.START_MD.exists():
    raise FileNotFoundError(
        f"start.md not found at {config.START_MD}. "
        "Copy example.start.md to start.md and edit it:\n"
        "  cp example.start.md start.md"
    )

_tmux = TmuxClient()
_cached_session: Session | None = None


def _get_session() -> Session:
    """Lazy-load the current tmux session (cached for the process lifetime)."""
    global _cached_session
    if _cached_session is None:
        pane_id = _tmux.get_pane_id()
        _cached_session = Session(pane_id, config.base_dir).ensure_dirs()
    return _cached_session


def _parse_delay(delay: str) -> timedelta:
    match = re.fullmatch(r"(\d+)\s*([dhm])", delay.strip().lower())
    if not match:
        raise ValueError(f"Invalid delay format: '{delay}'. Use e.g. '10m', '2h', '1d'.")
    value, unit = int(match.group(1)), match.group(2)
    if unit == "d":
        return timedelta(days=value)
    if unit == "h":
        return timedelta(hours=value)
    return timedelta(minutes=value)


mcp = FastMCP("selfcontrol-mcp")


@mcp.tool
def prompt_now(message: str) -> str:
    """Queue a prompt for immediate delivery (next scheduler cycle)."""
    try:
        session = _get_session()
    except NotInTmuxError as e:
        return str(e)
    filename = session.write_queue_file(Session.IMMEDIATE_TIMESTAMP, message)
    return f"Queued immediate prompt: {filename}"


@mcp.tool
def prompt_later(message: str, target_time: str | None = None, delay: str | None = None) -> str:
    """Queue a prompt for future delivery.

    Args:
        message: The prompt text to deliver.
        target_time: Absolute target time in ISO 8601 format (e.g. '2026-03-20T15:30:00').
        delay: Relative delay (e.g. '10m', '2h', '1d'). Ignored if target_time is provided.
    """
    try:
        session = _get_session()
    except NotInTmuxError as e:
        return str(e)

    if target_time is None and delay is None:
        return "Error: At least one of target_time or delay must be provided."

    dt = datetime.fromisoformat(target_time) if target_time else datetime.now() + _parse_delay(delay)
    timestamp_str = dt.strftime(Session.TIMESTAMP_FORMAT)
    filename = session.write_queue_file(timestamp_str, message)
    return f"Scheduled prompt for {dt.isoformat()}: {filename}"


@mcp.tool
def message_user(message: str, file_path: str | None = None) -> str:
    """Send a message to the user via Telegram. Use this for all communication — the user is NOT watching terminal output.

    Args:
        message: The message text to send.
        file_path: Optional absolute path to a file or image to send along with the message.
    """
    if not config.telegram_bot_token or not config.telegram_user_id:
        return "Error: Telegram not configured. Run setup.py to set bot token and user ID."

    # Build session prefix
    prefix = ""
    try:
        session = _get_session()
        encoded = SessionManager.encode_name(session.name)
        prefix = f"/{encoded}  {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
    except (NotInTmuxError, Exception):
        pass

    full_message = prefix + message
    telegram = TelegramClient(config.telegram_bot_token, config.telegram_user_id)

    if file_path:
        p = Path(file_path)
        if not p.exists():
            return f"Error: File not found: {file_path}"
        ext = p.suffix.lower()
        with open(p, "rb") as f:
            if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
                telegram.send_photo(f, caption=full_message)
            else:
                telegram.send_document(f, caption=full_message)
    else:
        telegram.send_message(full_message)

    return "Message sent to user."


@mcp.prompt
def start() -> str:
    """Returns the startup prompt from start.md to bootstrap an AI session."""
    return config.START_MD.read_text()


if __name__ == "__main__":
    mcp.run()
