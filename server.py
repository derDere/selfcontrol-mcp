import os
import re
import random
import string
import subprocess
from pathlib import Path
from datetime import datetime, timedelta

from fastmcp import FastMCP

REPO_DIR = Path(__file__).parent
START_MD = REPO_DIR / "start.md"

if not START_MD.exists():
    raise FileNotFoundError(
        f"start.md not found at {START_MD}. "
        "Copy example.start.md to start.md and edit it:\n"
        "  cp example.start.md start.md"
    )

BASE_DIR = Path("~/.ai-sessions").expanduser()


class NotInTmuxError(Exception):
    pass


def get_tmux_pane() -> str:
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#{session_name}:#{window_index}.#{pane_index}"],
            capture_output=True, text=True, timeout=5,
        )
    except FileNotFoundError:
        raise NotInTmuxError("tmux is not installed.")
    if result.returncode != 0:
        raise NotInTmuxError(
            "Not running inside a tmux session. "
            "selfcontrol-mcp requires tmux to function. "
            "Start Claude Code inside a tmux pane to enable self-prompting."
        )
    return result.stdout.strip()


def ensure_session_dir(pane_id: str) -> Path:
    session_dir = BASE_DIR / pane_id
    (session_dir / "queue").mkdir(parents=True, exist_ok=True)
    (session_dir / "input").mkdir(parents=True, exist_ok=True)
    return session_dir


def random_suffix(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def write_prompt_file(queue_dir: Path, timestamp_str: str, message: str) -> str:
    filename = f"{timestamp_str}_{random_suffix()}.txt"
    filepath = queue_dir / filename
    filepath.write_text(message)
    return filename


def parse_delay(delay: str) -> timedelta:
    match = re.fullmatch(r"(\d+)\s*([dhm])", delay.strip().lower())
    if not match:
        raise ValueError(f"Invalid delay format: '{delay}'. Use e.g. '10m', '2h', '1d'.")
    value, unit = int(match.group(1)), match.group(2)
    if unit == "d":
        return timedelta(days=value)
    elif unit == "h":
        return timedelta(hours=value)
    else:
        return timedelta(minutes=value)


_pane_id: str | None = None
_session_dir: Path | None = None


def get_session_dir() -> Path:
    global _pane_id, _session_dir
    if _session_dir is None:
        _pane_id = get_tmux_pane()
        _session_dir = ensure_session_dir(_pane_id)
    return _session_dir


mcp = FastMCP("selfcontrol-mcp")


@mcp.tool
def prompt_now(message: str) -> str:
    """Queue a prompt for immediate delivery (next scheduler cycle)."""
    try:
        session_dir = get_session_dir()
    except NotInTmuxError as e:
        return str(e)
    filename = write_prompt_file(
        session_dir / "queue",
        "19000101T000000",
        message,
    )
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
        session_dir = get_session_dir()
    except NotInTmuxError as e:
        return str(e)

    if target_time is None and delay is None:
        return "Error: At least one of target_time or delay must be provided."

    if target_time is not None:
        dt = datetime.fromisoformat(target_time)
    else:
        dt = datetime.now() + parse_delay(delay)

    timestamp_str = dt.strftime("%Y%m%dT%H%M%S")
    filename = write_prompt_file(session_dir / "queue", timestamp_str, message)
    return f"Scheduled prompt for {dt.isoformat()}: {filename}"


@mcp.prompt
def start() -> str:
    """Returns the startup prompt from start.md to bootstrap an AI session."""
    return START_MD.read_text()


if __name__ == "__main__":
    mcp.run()
