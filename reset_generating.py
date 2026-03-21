import subprocess
from pathlib import Path

BASE_DIR = Path("~/.ai-sessions").expanduser()


def main() -> None:
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#{session_name}:#{window_index}.#{pane_index}"],
            capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return

    if result.returncode != 0:
        return

    pane_id = result.stdout.strip()
    if not pane_id:
        return

    lock_path = BASE_DIR / pane_id / "generating.lock"
    if lock_path.exists():
        lock_path.unlink()


if __name__ == "__main__":
    main()
