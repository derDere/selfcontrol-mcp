"""Rate-limit state management."""

import json
from datetime import datetime
from pathlib import Path


class RateLimiter:
    """Reads / writes ``rate_limit.json`` in the sessions base directory."""

    def __init__(self, base_dir: Path):
        self.path = base_dir / "rate_limit.json"

    @property
    def is_limited(self) -> bool:
        return self.path.exists()

    def set_limit(
        self,
        error: str,
        details: str,
        session: str,
        msg_id: int | None = None,
    ) -> None:
        data: dict = {
            "detected_at": datetime.now().isoformat(),
            "error": error,
            "error_details": details,
            "session": session,
        }
        if msg_id is not None:
            data["telegram_msg_id"] = msg_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2) + "\n")

    def load(self) -> dict | None:
        """Load rate-limit data, or None if not limited."""
        if not self.path.exists():
            return None
        try:
            return json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def clear(self) -> bool:
        if self.path.exists():
            self.path.unlink()
            return True
        return False
