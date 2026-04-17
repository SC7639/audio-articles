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


# Session cookies that indicate a successful login per platform
_SESSION_COOKIE: dict[str, str] = {
    "substack": "substack.sid",
    "medium": "uid",
}

# URL prefixes that are part of the signin flow for each platform.
# When the browser is still on one of these, the session cookie may exist but
# authentication is not yet complete (e.g. Medium sets uid as an anonymous ID).
_SIGNIN_URL_PREFIXES: dict[str, tuple[str, ...]] = {
    "medium": (
        "https://medium.com/m/signin",
        "https://medium.com/m/callback",
        "https://accounts.google.com/",
        "https://appleid.apple.com/",
        "https://www.facebook.com/login",
    ),
}


_SENTINEL = object()  # distinguishes "no initial_value provided" from "initial_value was None"


def _get_cookie_value(context, name: str) -> str | None:
    """Return the value of a named cookie from the browser context, or None."""
    return next((c["value"] for c in context.cookies() if c["name"] == name), None)


def _has_session_cookie(context, page, platform: str, *, initial_value: str | None = _SENTINEL) -> bool:
    """Return True if login is complete.

    Checks three conditions:
    1. The expected session cookie exists.
    2. Its value has changed from the pre-login baseline (catches platforms like Medium
       that set an anonymous session cookie before the user authenticates).
    3. The browser is no longer on a signin/OAuth page.
    """
    expected = _SESSION_COOKIE.get(platform)
    if expected is None:
        return False
    current_value = _get_cookie_value(context, expected)
    if current_value is None:
        return False
    # If we captured the pre-login cookie value, require it to have changed.
    # initial_value=None means the cookie was absent at page load; any value now is authenticated.
    # initial_value=<str> means an anonymous cookie existed; wait for it to change.
    if initial_value is not _SENTINEL and current_value == initial_value:
        return False
    # URL guard: verify the browser has left signin/OAuth pages.
    signin_prefixes = _SIGNIN_URL_PREFIXES.get(platform, ())
    if signin_prefixes and any(page.url.startswith(p) for p in signin_prefixes):
        return False
    return True


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

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(login_url)

        # For platforms that set an anonymous session cookie before the user
        # authenticates (e.g. Medium sets `uid` during the Cloudflare challenge),
        # capture the initial cookie value so we can wait for it to change.
        initial_value: object = _SENTINEL
        if platform in _SIGNIN_URL_PREFIXES:
            page.wait_for_load_state("domcontentloaded")
            cookie_name = _SESSION_COOKIE[platform]
            initial_value = _get_cookie_value(context, cookie_name)

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if _has_session_cookie(context, page, platform, initial_value=initial_value):
                break
            time.sleep(1)
        else:
            browser.close()
            raise LoginError("Login timed out. Please try again.")

        cookies = context.cookies()
        browser.close()

    SessionStore(session_dir).save(platform, cookies)
