import json
import os
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
        self._dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self._path(platform)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(cookies))

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


# ── Platform login config ─────────────────────────────────────────────────

_PLATFORMS = frozenset({"substack", "medium"})

_PLATFORM_LOGIN_URLS: dict[str, str] = {
    "substack": "https://substack.com/sign-in",
    "medium": "https://medium.com/m/signin",
}


def _is_logged_in_substack(url: str) -> bool:
    return "substack.com/feed" in url or "substack.com/inbox" in url


def _is_logged_in_medium(url: str) -> bool:
    # Medium redirects to /me/... or the homepage root after successful login
    return "medium.com" in url and (
        "/me/" in url or url.rstrip("/").endswith("medium.com")
    )


_IS_LOGGED_IN: dict[str, object] = {
    "substack": _is_logged_in_substack,
    "medium": _is_logged_in_medium,
}


# ── Interactive login ─────────────────────────────────────────────────────

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None  # type: ignore[assignment]


def login_interactive(
    platform: str,
    *,
    session_dir: Path | None = None,
    timeout: int = 300,
) -> None:
    """Open a headed Chromium browser, wait for the user to log in, then save cookies.

    Args:
        platform: 'substack' or 'medium'
        session_dir: override cookie storage directory (used in tests)
        timeout: seconds to wait for login before raising LoginError
    """
    platform = platform.lower()
    if platform not in _PLATFORMS:
        raise LoginError(
            f"Unknown platform '{platform}'. Supported: {', '.join(sorted(_PLATFORMS))}"
        )

    if sync_playwright is None:
        raise LoginError(
            "Playwright is not installed. Run:\n"
            "  pip install 'audio-articles[login]'\n"
            "  playwright install chromium"
        )

    login_url = _PLATFORM_LOGIN_URLS[platform]
    is_logged_in = _IS_LOGGED_IN[platform]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(login_url)

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if is_logged_in(page.url):
                break
            time.sleep(1)
        else:
            browser.close()
            raise LoginError("Login timed out. Please try again.")

        cookies = context.cookies()
        browser.close()

    SessionStore(session_dir).save(platform, cookies)
