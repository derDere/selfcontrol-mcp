"""Background prompt scheduler — polls session queues and dispatches prompts via tmux."""

import logging
import time
from datetime import datetime
from pathlib import Path

from lib import Config, Session, SessionManager, TmuxClient, RateLimiter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("scheduler")


class Scheduler:
    def __init__(self, config: Config):
        self.config = config
        self.tmux = TmuxClient()
        self.sessions = SessionManager(config.base_dir)
        self.rate_limiter = RateLimiter(config.base_dir)
        self._last_prompt_time: dict[str, datetime] = {}

    @staticmethod
    def sanitize_prompt(text: str) -> str:
        """Strip accidental leading slashes: ``//`` → ``/``, ``/`` → stripped."""
        if text.startswith("//"):
            return text[1:]
        if text.startswith("/"):
            return text[1:]
        return text

    def process_session(self, session: Session) -> None:
        if session.is_locked and not session.is_lock_stale(self.config.generating_timeout_minutes):
            log.debug("Skipping %s — generating lock active", session.name)
            return

        utc_now = datetime.utcnow().strftime("%Y-%m-%d %H:%M utc")
        parts: list[str] = []
        consumed: list[Path] = []

        # Collect due AI prompts
        for f in session.get_due_queue_files():
            text = f.read_text().strip()
            if text:
                parts.append(f"[{utc_now}] AI: {self.sanitize_prompt(text)}")
                consumed.append(f)

        # Collect user input prompts
        for f in session.get_input_files():
            text = f.read_text().strip()
            if text:
                parts.append(f"[{utc_now}] User: {self.sanitize_prompt(text)}")
                consumed.append(f)

        # Fall back to default prompt after configured interval
        if not parts:
            last = self._last_prompt_time.get(session.name)
            if last is not None:
                elapsed = (datetime.now() - last).total_seconds() / 60
                if elapsed < self.config.default_prompt_interval_minutes:
                    log.debug("Skipping default for %s — %.1f min since last prompt", session.name, elapsed)
                    return
            parts.append(f"[{utc_now}] {self.config.default_prompt}")
            source = "default"
        else:
            source = f"bundled({len(parts)})"

        prompt_text = "\n\n---\n\n".join(parts)
        log.info("Sending to %s [%s]: %.80s", session.name, source, prompt_text.replace("\n", " "))

        if not self.tmux.send_keys(session.name, prompt_text):
            log.error("Failed to send to %s", session.name)
            return

        self._last_prompt_time[session.name] = datetime.now()
        session.set_lock()
        session.log_history(source, prompt_text, session.name)

        for f in consumed:
            f.unlink(missing_ok=True)

    def run(self) -> None:
        interval = self.config.check_interval_seconds
        log.info("Scheduler started — base_dir=%s, interval=%ds", self.config.base_dir, interval)

        while True:
            if self.rate_limiter.is_limited:
                log.info("Rate limit active — skipping all sessions (use /unlimit to resume)")
                time.sleep(interval)
                continue

            for session in self.sessions.list_sessions():
                try:
                    self.process_session(session)
                except Exception:
                    log.exception("Error processing session %s", session.name)

            time.sleep(interval)


if __name__ == "__main__":
    Scheduler(Config()).run()
