"""Manages all sessions and the session-map file."""

import json
from pathlib import Path

from lib.session import Session


class SessionManager:
    """Discovers sessions on disk and maintains the encoded-name ↔ real-name map."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.map_path = base_dir / "session_map.json"

    def get_session(self, name: str) -> Session:
        return Session(name, self.base_dir)

    def list_sessions(self) -> list[Session]:
        if not self.base_dir.is_dir():
            return []
        return [
            Session(entry.name, self.base_dir)
            for entry in sorted(self.base_dir.iterdir())
            if entry.is_dir() and entry.name != "__pycache__"
        ]

    # --- Session map ---

    def load_map(self) -> dict:
        if self.map_path.exists():
            with open(self.map_path) as f:
                return json.load(f)
        return {}

    def save_map(self, mapping: dict) -> None:
        self.map_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.map_path, "w") as f:
            json.dump(mapping, f, indent=2)
            f.write("\n")

    def refresh_map(self) -> dict:
        mapping = {
            self.encode_name(s.name): s.name
            for s in self.list_sessions()
        }
        self.save_map(mapping)
        return mapping

    def decode_command(self, cmd: str) -> str | None:
        return self.load_map().get(cmd)

    # --- Static helpers ---

    @staticmethod
    def encode_name(name: str) -> str:
        """``'work:0.1'`` → ``'s_work_0_1'``"""
        return "s_" + name.replace(":", "_").replace(".", "_")

    @staticmethod
    def escape_markdown(encoded: str) -> str:
        """Escape underscores for Telegram Markdown."""
        return encoded.replace("_", "\\_")
