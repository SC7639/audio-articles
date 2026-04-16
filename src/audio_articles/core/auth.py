import json
import re
import time
from pathlib import Path

from .exceptions import LoginError

# ── Session storage ───────────────────────────────────────────────────────

_SESSION_DIR = Path.home() / ".config" / "audio-articles" / "sessions"


class SessionStore:
    """Persists Playwright cookie lists per platform as JSON files."""

    def __init__(self, session_dir: Path | None = None) -> None:
        self._dir = session_dir or _SESSION_DIR

    def _path(self, platform: str) -> Path:
        return self._dir / f"{platform}.json"

    def save(self, platform: str, cookies: list[dict]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path(platform).write_text(json.dumps(cookies), encoding="utf-8")

    def load(self, platform: str) -> list[dict] | None:
        p = self._path(platform)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def delete(self, platform: str) -> None:
        p = self._path(platform)
        if p.exists():
            p.unlink()

    def delete_all(self) -> None:
        if not self._dir.exists():
            return
        for p in self._dir.glob("*.json"):
            p.unlink()
