"""Tmux CLI wrapper."""

import subprocess
import time


class NotInTmuxError(Exception):
    pass


class TmuxClient:
    """Wraps all tmux subprocess interactions."""

    _PANE_CMD = [
        "tmux", "display-message", "-p",
        "#{session_name}:#{window_index}.#{pane_index}",
    ]

    def get_pane_id(self) -> str:
        """Return the current tmux pane target. Raises NotInTmuxError if not in tmux."""
        try:
            result = subprocess.run(
                self._PANE_CMD,
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

    def get_pane_id_safe(self) -> str:
        """Return the pane ID, or ``'unknown'`` when not inside tmux."""
        try:
            return self.get_pane_id()
        except NotInTmuxError:
            return "unknown"

    def send_keys(self, pane: str, text: str) -> bool:
        """Send *text* to *pane* in literal mode, then press Enter after a short delay."""
        try:
            subprocess.run(
                ["tmux", "send-keys", "-t", pane, "-l", text],
                check=True, capture_output=True, text=True, timeout=10,
            )
            time.sleep(0.5)
            subprocess.run(
                ["tmux", "send-keys", "-t", pane, "Enter"],
                check=True, capture_output=True, text=True, timeout=10,
            )
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return False

    def send_enter(self, pane: str) -> bool:
        """Send a bare Enter keystroke to *pane*."""
        try:
            subprocess.run(
                ["tmux", "send-keys", "-t", pane, "Enter"],
                check=True, capture_output=True, text=True, timeout=5,
            )
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            return False
