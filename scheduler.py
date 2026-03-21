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


def get_due_queue_file(queue_dir: Path) -> Path | None:
    now = datetime.now()
    candidates = []
    for f in queue_dir.iterdir():
        if not f.is_file() or not f.name.endswith(".txt"):
            continue
        ts = parse_queue_timestamp(f.name)
        if ts is not None and ts <= now:
            candidates.append((f.name, f))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


def get_oldest_input_file(input_dir: Path) -> Path | None:
    files = [f for f in input_dir.iterdir() if f.is_file()]
    if not files:
        return None
    files.sort(key=lambda f: f.stat().st_mtime)
    return files[0]


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


def process_session(session_dir: Path, config: dict) -> None:
    pane_target = session_dir.name
    timeout_minutes = config.get("generating_timeout_minutes", 30)

    lock_path = session_dir / "generating.lock"
    if lock_path.exists() and not is_lock_stale(lock_path, timeout_minutes):
        log.debug("Skipping %s — generating lock active", pane_target)
        return

    queue_dir = session_dir / "queue"
    input_dir = session_dir / "input"

    prompt_text = None
    source = None
    consumed_file = None

    if queue_dir.is_dir():
        due_file = get_due_queue_file(queue_dir)
        if due_file:
            prompt_text = due_file.read_text()
            source = "queue"
            consumed_file = due_file

    if prompt_text is None and input_dir.is_dir():
        input_file = get_oldest_input_file(input_dir)
        if input_file:
            prompt_text = input_file.read_text()
            source = "input"
            consumed_file = input_file

    if prompt_text is None:
        default_interval = config.get("default_prompt_interval_minutes", 5)
        last_time = _last_prompt_time.get(pane_target)
        if last_time is not None:
            elapsed = (datetime.now() - last_time).total_seconds() / 60
            if elapsed < default_interval:
                log.debug("Skipping default for %s — last prompt %.1f min ago (interval: %d min)",
                          pane_target, elapsed, default_interval)
                return
        prompt_text = config.get("default_prompt", "Continue.")
        source = "default"

    if not prompt_text.strip():
        log.warning("Empty prompt for %s from %s, skipping", pane_target, source)
        if consumed_file:
            consumed_file.unlink(missing_ok=True)
        return

    # Sanitize leading slashes: // → / (real command), / → stripped (accidental command)
    if prompt_text.startswith("//"):
        prompt_text = prompt_text[1:]
    elif prompt_text.startswith("/"):
        prompt_text = prompt_text[1:]

    log.info("Sending to %s [%s]: %.80s", pane_target, source, prompt_text.replace("\n", " "))

    if not send_prompt(pane_target, prompt_text):
        return

    _last_prompt_time[pane_target] = datetime.now()
    set_lock(session_dir)
    log_history(session_dir, source, prompt_text, pane_target)

    if consumed_file:
        consumed_file.unlink(missing_ok=True)


def main() -> None:
    config = load_config()
    base_dir = Path(config.get("base_dir", "~/.ai-sessions")).expanduser()
    interval = config.get("check_interval_seconds", 60)

    log.info("Scheduler started — base_dir=%s, interval=%ds", base_dir, interval)

    while True:
        if base_dir.is_dir():
            for entry in sorted(base_dir.iterdir()):
                if entry.is_dir():
                    try:
                        process_session(entry, config)
                    except Exception:
                        log.exception("Error processing session %s", entry.name)

        time.sleep(interval)


if __name__ == "__main__":
    main()
