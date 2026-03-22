import os
import time
import subprocess
import logging
from pathlib import Path
from datetime import datetime

import yaml

# Tracks when a prompt was last sent to each session (any type: queue, input, or default)
_last_prompt_time: dict[str, datetime] = {}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("scheduler")

SCRIPT_DIR = Path(__file__).parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def parse_queue_timestamp(filename: str) -> datetime | None:
    stem = Path(filename).stem
    parts = stem.split("_", 1)
    if not parts:
        return None
    try:
        return datetime.strptime(parts[0], "%Y%m%dT%H%M%S")
    except ValueError:
        return None


def is_lock_stale(lock_path: Path, timeout_minutes: int) -> bool:
    try:
        content = lock_path.read_text().strip()
        lock_time = datetime.fromisoformat(content)
        age_minutes = (datetime.now() - lock_time).total_seconds() / 60
        return age_minutes >= timeout_minutes
    except (ValueError, OSError):
        return True


def get_due_queue_files(queue_dir: Path) -> list[Path]:
    """Return all queue files that are due, sorted chronologically."""
    now = datetime.now()
    candidates = []
    for f in queue_dir.iterdir():
        if not f.is_file() or not f.name.endswith(".txt"):
            continue
        ts = parse_queue_timestamp(f.name)
        if ts is not None and ts <= now:
            candidates.append((f.name, f))
    candidates.sort(key=lambda x: x[0])
    return [f for _, f in candidates]


def get_all_input_files(input_dir: Path) -> list[Path]:
    """Return all input files, sorted by modification time (oldest first)."""
    files = [f for f in input_dir.iterdir() if f.is_file()]
    files.sort(key=lambda f: f.stat().st_mtime)
    return files


def send_prompt(pane_target: str, prompt_text: str) -> bool:
    try:
        subprocess.run(
            ["tmux", "send-keys", "-t", pane_target, "-l", prompt_text],
            check=True, capture_output=True, text=True, timeout=10,
        )
        subprocess.run(
            ["tmux", "send-keys", "-t", pane_target, "Enter"],
            check=True, capture_output=True, text=True, timeout=10,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        log.error("Failed to send to %s: %s", pane_target, e)
        return False


def set_lock(session_dir: Path) -> None:
    lock_path = session_dir / "generating.lock"
    lock_path.write_text(datetime.now().isoformat())


def log_history(session_dir: Path, source: str, prompt_text: str, pane_target: str) -> None:
    summary = prompt_text[:100].replace("\n", " ")
    entry = f"[{datetime.now().isoformat()}] [{source}] {summary} -> {pane_target}\n"
    history_path = session_dir / "history.log"
    with open(history_path, "a") as f:
        f.write(entry)


def sanitize_prompt(text: str) -> str:
    """Sanitize leading slashes: // → / (real command), / → stripped (accidental command)."""
    if text.startswith("//"):
        return text[1:]
    elif text.startswith("/"):
        return text[1:]
    return text


def process_session(session_dir: Path, config: dict) -> None:
    pane_target = session_dir.name
    timeout_minutes = config.get("generating_timeout_minutes", 30)

    lock_path = session_dir / "generating.lock"
    if lock_path.exists() and not is_lock_stale(lock_path, timeout_minutes):
        log.debug("Skipping %s — generating lock active", pane_target)
        return

    queue_dir = session_dir / "queue"
    input_dir = session_dir / "input"

    utc_now = datetime.utcnow().strftime("%Y-%m-%d %H:%M utc")
    parts: list[str] = []
    consumed_files: list[Path] = []

    # Collect all due AI prompts (chronological)
    if queue_dir.is_dir():
        for f in get_due_queue_files(queue_dir):
            text = f.read_text().strip()
            if text:
                text = sanitize_prompt(text)
                parts.append(f"[{utc_now}] AI: {text}")
                consumed_files.append(f)

    # Collect all user input prompts (chronological)
    if input_dir.is_dir():
        for f in get_all_input_files(input_dir):
            text = f.read_text().strip()
            if text:
                text = sanitize_prompt(text)
                parts.append(f"[{utc_now}] User: {text}")
                consumed_files.append(f)

    # If nothing due, fall back to default prompt after configured interval
    if not parts:
        default_interval = config.get("default_prompt_interval_minutes", 5)
        last_time = _last_prompt_time.get(pane_target)
        if last_time is not None:
            elapsed = (datetime.now() - last_time).total_seconds() / 60
            if elapsed < default_interval:
                log.debug("Skipping default for %s — last prompt %.1f min ago (interval: %d min)",
                          pane_target, elapsed, default_interval)
                return
        default_text = config.get("default_prompt", "Continue.")
        parts.append(f"[{utc_now}] {default_text}")
        source = "default"
    else:
        source = f"bundled({len(parts)})"

    prompt_text = "\n\n---\n\n".join(parts)

    log.info("Sending to %s [%s]: %.80s", pane_target, source, prompt_text.replace("\n", " "))

    if not send_prompt(pane_target, prompt_text):
        return

    _last_prompt_time[pane_target] = datetime.now()
    set_lock(session_dir)
    log_history(session_dir, source, prompt_text, pane_target)

    for f in consumed_files:
        f.unlink(missing_ok=True)


def is_rate_limited(base_dir: Path) -> bool:
    """Check if rate_limit.json exists. Returns True if scheduler should skip all sessions."""
    rate_limit_path = base_dir / "rate_limit.json"
    if rate_limit_path.exists():
        log.info("Rate limit active — skipping all sessions (use /unlimit to resume)")
        return True
    return False


def main() -> None:
    config = load_config()
    base_dir = Path(config.get("base_dir", "~/.ai-sessions")).expanduser()
    interval = config.get("check_interval_seconds", 60)

    log.info("Scheduler started — base_dir=%s, interval=%ds", base_dir, interval)

    while True:
        if base_dir.is_dir():
            if is_rate_limited(base_dir):
                time.sleep(interval)
                continue

            for entry in sorted(base_dir.iterdir()):
                if entry.is_dir() and entry.name != "__pycache__":
                    try:
                        process_session(entry, config)
                    except Exception:
                        log.exception("Error processing session %s", entry.name)

        time.sleep(interval)


if __name__ == "__main__":
    main()
