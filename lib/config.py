"""Centralized configuration loaded from config.yaml."""

from pathlib import Path

import yaml

REPO_DIR = Path(__file__).parent.parent


class Config:
    """Loads and provides typed access to config.yaml settings."""

    CONFIG_PATH = REPO_DIR / "config.yaml"
    START_MD = REPO_DIR / "start.md"

    def __init__(self, path: Path | None = None):
        self._path = path or self.CONFIG_PATH
        self._data: dict = {}
        if self._path.exists():
            self.reload()

    def reload(self) -> None:
        with open(self._path) as f:
            self._data = yaml.safe_load(f) or {}

    @property
    def default_prompt(self) -> str:
        return self._data.get("default_prompt", "Continue.")

    @property
    def base_dir(self) -> Path:
        return Path(self._data.get("base_dir", "~/.ai-sessions")).expanduser()

    @property
    def check_interval_seconds(self) -> int:
        return self._data.get("check_interval_seconds", 10)

    @property
    def default_prompt_interval_minutes(self) -> int:
        return self._data.get("default_prompt_interval_minutes", 5)

    @property
    def generating_timeout_minutes(self) -> int:
        return self._data.get("generating_timeout_minutes", 30)

    @property
    def permission_timeout_minutes(self) -> int:
        return self._data.get("permission_timeout_minutes", 10)

    @property
    def permission_timeout_message(self) -> str:
        return self._data.get("permission_timeout_message", "Permission denied (timeout).")

    @property
    def telegram_bot_token(self) -> str:
        return self._data.get("telegram_bot_token", "")

    @property
    def telegram_user_id(self) -> int:
        return self._data.get("telegram_user_id", 0)
