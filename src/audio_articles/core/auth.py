import json
import time
from pathlib import Path
from urllib.parse import urlparse

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
            data = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return None
            return data
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


# ── Known Medium custom domains ───────────────────────────────────────────

MEDIUM_CUSTOM_DOMAINS: frozenset[str] = frozenset({
    "towardsdatascience.com",
    "betterprogramming.pub",
    "uxdesign.cc",
    "itnext.io",
    "levelup.gitconnected.com",
    "bootcamp.uxdesign.cc",
    "proandroiddev.com",
    "blog.devgenius.io",
})

def _platform_for_url(url: str) -> str | None:
    """Return 'substack', 'medium', or None based on the URL domain."""
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return None
    if host == "substack.com" or host.endswith(".substack.com"):
        return "substack"
    if host == "medium.com" or host.endswith(".medium.com"):
        return "medium"
    if host in MEDIUM_CUSTOM_DOMAINS:
        return "medium"
    return None


def _cookies_list_to_dict(cookies: list[dict]) -> dict[str, str]:
    return {c["name"]: c["value"] for c in cookies if "name" in c and "value" in c}


def get_cookies_for_url(
    url: str,
    *,
    session_dir: Path | None = None,
) -> dict[str, str] | None:
    """Return saved session cookies for the platform matching `url`, or None."""
    platform = _platform_for_url(url)
    if platform is None:
        return None
    cookies = SessionStore(session_dir).load(platform)
    if cookies is None:
        return None
    return _cookies_list_to_dict(cookies)


def get_medium_cookies(*, session_dir: Path | None = None) -> dict[str, str] | None:
    """Return saved Medium cookies regardless of URL (used for post-fetch detection)."""
    cookies = SessionStore(session_dir).load("medium")
    if cookies is None:
        return None
    return _cookies_list_to_dict(cookies)
