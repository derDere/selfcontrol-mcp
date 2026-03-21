"""Shared session name encoding/decoding and tmux pane detection."""

import json
import subprocess
from pathlib import Path


def encode_session_name(name: str) -> str:
    """Encode a tmux pane target (e.g. 'work:0.1') to a Telegram command suffix (e.g. 's_work_0_1')."""
    return "s_" + name.replace(":", "_").replace(".", "_")


def decode_session_command(cmd: str, session_map: dict) -> str | None:
    """Decode a Telegram command suffix back to a real session name using the session map."""
    return session_map.get(cmd)


def escape_for_markdown(encoded: str) -> str:
    """Escape underscores in encoded session names for Telegram Markdown."""
    return encoded.replace("_", "\\_")


def load_session_map(session_map_path: Path) -> dict:
    """Load the session map from disk."""
    if session_map_path.exists():
        with open(session_map_path) as f:
            return json.load(f)
    return {}


def save_session_map(mapping: dict, session_map_path: Path) -> None:
    """Save the session map to disk."""
    session_map_path.parent.mkdir(parents=True, exist_ok=True)
    with open(session_map_path, "w") as f:
        json.dump(mapping, f, indent=2)
        f.write("\n")


def refresh_session_map(base_dir: Path, session_map_path: Path) -> dict:
    """Scan session directories and rebuild the session map."""
    mapping = {}
    if base_dir.is_dir():
        for entry in sorted(base_dir.iterdir()):
            if entry.is_dir() and entry.name != "__pycache__":
                encoded = encode_session_name(entry.name)
                mapping[encoded] = entry.name
    save_session_map(mapping, session_map_path)
    return mapping


def get_pane_id() -> str:
    """Detect the current tmux pane target (e.g. 'work:0.1'). Returns 'unknown' if not in tmux."""
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#{session_name}:#{window_index}.#{pane_index}"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return "unknown"
