"""Single AI session with its on-disk file structure."""

import random
import string
from datetime import datetime
from pathlib import Path


class Session:
    """Represents one session directory under ``~/.ai-sessions/<pane_id>/``."""

    TIMESTAMP_FORMAT = "%Y%m%dT%H%M%S"
    IMMEDIATE_TIMESTAMP = "19000101T000000"

    def __init__(self, name: str, base_dir: Path):
        self.name = name
        self.path = base_dir / name
        self.queue_dir = self.path / "queue"
        self.input_dir = self.path / "input"
        self.permissions_dir = self.path / "permissions"
        self.lock_path = self.path / "generating.lock"
        self.history_path = self.path / "history.log"

    def ensure_dirs(self) -> "Session":
        """Create queue/ and input/ subdirectories (idempotent)."""
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        self.input_dir.mkdir(parents=True, exist_ok=True)
        return self

    # --- Lock operations ---

    @property
    def is_locked(self) -> bool:
        return self.lock_path.exists()

    def is_lock_stale(self, timeout_minutes: int) -> bool:
        try:
            lock_time = datetime.fromisoformat(self.lock_path.read_text().strip())
            age = (datetime.now() - lock_time).total_seconds() / 60
            return age >= timeout_minutes
        except (ValueError, OSError):
            return True

    def set_lock(self) -> None:
        self.lock_path.write_text(datetime.now().isoformat())

    def clear_lock(self) -> bool:
        """Remove the lock file. Returns True if a lock was actually removed."""
        if self.lock_path.exists():
            self.lock_path.unlink()
            return True
        return False

    # --- History ---

    def log_history(self, source: str, text: str, pane: str) -> None:
        summary = text[:100].replace("\n", " ")
        entry = f"[{datetime.now().isoformat()}] [{source}] {summary} -> {pane}\n"
        with open(self.history_path, "a") as f:
            f.write(entry)

    # --- Queue files ---

    @staticmethod
    def _parse_queue_timestamp(filename: str) -> datetime | None:
        parts = Path(filename).stem.split("_", 1)
        if not parts:
            return None
        try:
            return datetime.strptime(parts[0], Session.TIMESTAMP_FORMAT)
        except ValueError:
            return None

    def get_due_queue_files(self) -> list[Path]:
        """Return queue files whose target time has passed, sorted chronologically."""
        if not self.queue_dir.is_dir():
            return []
        now = datetime.now()
        candidates = []
        for f in self.queue_dir.iterdir():
            if not f.is_file() or not f.name.endswith(".txt"):
                continue
            ts = self._parse_queue_timestamp(f.name)
            if ts is not None and ts <= now:
                candidates.append((f.name, f))
        candidates.sort(key=lambda x: x[0])
        return [f for _, f in candidates]

    def get_input_files(self) -> list[Path]:
        """Return input files sorted by modification time (oldest first)."""
        if not self.input_dir.is_dir():
            return []
        files = [f for f in self.input_dir.iterdir() if f.is_file()]
        files.sort(key=lambda f: f.stat().st_mtime)
        return files

    # --- File writing helpers ---

    @staticmethod
    def random_suffix(length: int = 6) -> str:
        return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))

    def write_queue_file(self, timestamp_str: str, message: str) -> str:
        """Write a prompt file to queue/. Returns the filename."""
        filename = f"{timestamp_str}_{self.random_suffix()}.txt"
        (self.queue_dir / filename).write_text(message)
        return filename

    def write_input_file(self, content: str) -> Path | None:
        """Write a user-input file to input/. Returns the path, or None if dir missing."""
        if not self.input_dir.is_dir():
            return None
        timestamp = datetime.now().strftime(self.TIMESTAMP_FORMAT)
        filename = f"{timestamp}_{self.random_suffix()}.txt"
        filepath = self.input_dir / filename
        filepath.write_text(content)
        return filepath

    # --- Permissions ---

    def write_permission_response(self, req_id: str, decision: str) -> bool:
        self.permissions_dir.mkdir(parents=True, exist_ok=True)
        try:
            (self.permissions_dir / req_id).write_text(decision)
            return True
        except OSError:
            return False

    def read_permission_response(self, req_id: str) -> str | None:
        """Read and delete a permission response file. Returns the decision or None."""
        resp_path = self.permissions_dir / req_id
        if not resp_path.exists():
            return None
        try:
            decision = resp_path.read_text().strip()
            resp_path.unlink(missing_ok=True)
            return decision if decision in ("allow", "always", "deny") else None
        except OSError:
            return None
