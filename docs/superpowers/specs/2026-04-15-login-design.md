# Login Feature Design — Substack & Medium

## Context

`audio-articles` can already fetch paywalled articles if the user manually exports a Netscape cookie file from their browser and passes `--cookies <file>`. This works but is cumbersome — users must install a browser extension, remember to re-export when sessions expire, and pass the flag every time.

This feature replaces that workflow: `audio-articles login substack` (or `medium`) opens the real browser, the user signs in normally, and the app saves the session. Future converts happen automatically without any flags.

---

## Scope

- CLI only. The web API (`/api/v1/convert`) remains stateless and unchanged.
- Supports: Substack (including paywalled posts), Medium (including member-only stories), and well-known Medium custom-domain publications.
- Playwright is used for all login flows (headed browser, no credential storage, handles 2FA/CAPTCHA naturally).
- Cookies are stored in plain JSON at `~/.config/audio-articles/sessions/{platform}.json`. No encryption — same trust level as a browser profile directory.

---

## User-Facing Commands

```
audio-articles login [substack|medium]     Open browser, user logs in, session saved
audio-articles logout [substack|medium]    Delete saved session for that platform
audio-articles logout --all               Delete all saved sessions
```

After `login`, all `convert` and `ask` commands that fetch a matching URL apply the saved cookies automatically — no flags needed.

---

## Architecture

```
src/audio_articles/core/
├── auth.py          NEW — SessionStore + Playwright login flow + domain detection
├── fetcher.py       CHANGE — auto-load cookies; Medium URL detection + extraction
└── exceptions.py    CHANGE — add LoginError

cli/main.py          CHANGE — add login / logout commands
pyproject.toml       CHANGE — add [login] optional extra with playwright
```

---

## `auth.py` — Module Design

### Session storage

```
~/.config/audio-articles/sessions/
├── substack.json     # Playwright cookie list for substack.com
└── medium.json       # Playwright cookie list for medium.com
```

Each file is a JSON array of Playwright cookie dicts:
```json
[{"name": "substack.sid", "value": "...", "domain": ".substack.com", ...}]
```

A helper converts this to `dict[str, str]` (name → value) for `curl_cffi`.

### `SessionStore`

```python
class SessionStore:
    _config_dir: Path  # ~/.config/audio-articles/sessions

    def save(platform: str, cookies: list[dict]) -> None
    def load(platform: str) -> list[dict] | None
    def delete(platform: str) -> None
    def delete_all() -> None
```

### `login_interactive(platform: str) -> None`

1. Verify `playwright` is importable; raise `LoginError` with install instructions if not.
2. Import `playwright.sync_api` (deferred import — only when user runs `login`).
3. Determine login URL and "logged-in" detection condition:
   - Substack: `https://substack.com/sign-in`, wait until URL contains `/feed` or `/inbox` or cookies include `substack.sid`
   - Medium: `https://medium.com/m/signin`, wait until URL is `medium.com` root or cookies include `uid`
4. Open Playwright in headed mode (`chromium.launch(headless=False)`).
5. Navigate to login URL.
6. Wait until the condition is met (timeout: 5 minutes to give user time to log in and handle 2FA).
7. Extract all cookies from the browser context.
8. Save to `SessionStore`.
9. Close browser.

### `get_cookies_for_url(url: str) -> dict[str, str] | None`

Maps a URL to a platform, loads saved cookies, returns them as `{name: value}`.

Platform detection order:
1. Substack: URL matches `*.substack.com`
2. Medium: URL matches `medium.com` or `*.medium.com`
3. Medium custom domain: URL domain is in `MEDIUM_CUSTOM_DOMAINS` constant
4. Returns `None` if no platform matched or no session saved

### Medium custom domain list

```python
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
```

### Post-fetch Medium detection (fallback)

If a URL didn't match any known pattern but the fetched HTML contains either:
- A script src containing `cdn-client.medium.com`, or
- `<meta property="og:site_name" content="Medium">`

...then re-fetch with saved Medium cookies (if any). This handles unknown custom domains.

`fetcher.py` calls this after an initial fetch returns truncated content (< 200 words and paywall markers detected).

---

## `fetcher.py` Changes

### Auto-cookie loading

In `fetch_and_extract()`, before the HTTP call:

```python
if cookies is None:
    from .auth import get_cookies_for_url
    cookies = get_cookies_for_url(url)  # None if no saved session
```

This means the `cookies` parameter remains optional and unchanged — existing callers pass explicit cookies as before; new behaviour activates only when no cookies are given.

### Medium extraction

Add `_MEDIUM_URL_RE` to detect `medium.com` / `*.medium.com` URLs.

```python
_MEDIUM_URL_RE = re.compile(
    r"^https?://(?:[^/]+\.)?medium\.com/", re.IGNORECASE
)
```

Medium articles are standard HTML — `trafilatura` can extract them. The only difference from generic HTML is:
- Members-only articles are fully rendered in HTML when cookies carry a valid `uid` + `sid` session.
- No API rewrite needed (unlike Substack). `_extract_from_html` handles them.

The routing in `fetch_and_extract()` becomes:

```python
if _SUBSTACK_POST_RE.match(url):
    return _fetch_substack_api(...)
# Medium falls through to the standard HTML path with auto-loaded cookies
raw_html = _fetch_html(url, ...)
return _extract_from_html(raw_html, ...)
```

The post-fetch custom-domain detection hook (described above) is added after `_extract_from_html` if the result has very few words and the HTML has Medium markers — it retries with Medium cookies.

---

## CLI Changes

```python
@app.command()
def login(
    platform: str,   # "substack" or "medium"
) -> None:
    """Open a browser to log in to Substack or Medium and save the session."""

@app.command()
def logout(
    platform: str | None = None,   # "substack", "medium", or None
    all_: bool = Option(False, "--all"),
) -> None:
    """Delete a saved login session."""
```

`login` prints clear guidance: what's about to happen, what the user should do in the browser, and a success/failure message after.

---

## `pyproject.toml` Changes

Add optional `login` extra:

```toml
[project.optional-dependencies]
login = ["playwright>=1.44"]
```

`playwright` is intentionally optional — users who never need paywall access don't need the dependency or the browser binaries. The `login_interactive` function raises a clear `LoginError` if `playwright` is not installed, with the exact install command.

---

## Error Handling

| Scenario | Behaviour |
|---|---|
| `playwright` not installed | `LoginError` with message: "Run: pip install audio-articles[login] && playwright install chromium" |
| User closes browser before login completes | `LoginError`: "Browser closed before login completed." |
| Login timeout (5 minutes) | `LoginError`: "Login timed out. Please try again." |
| No saved session for URL | Silent — `get_cookies_for_url` returns `None`, fetch proceeds without cookies |
| Corrupt/expired session file | Load silently returns `None`, fetch proceeds without cookies |

---

## Testing

- `tests/test_auth.py`:
  - `test_session_store_round_trip` — save/load/delete
  - `test_session_store_delete_all` — all files removed
  - `test_get_cookies_for_url_substack` — substack URL → substack cookies
  - `test_get_cookies_for_url_medium` — medium.com URL → medium cookies
  - `test_get_cookies_for_url_custom_domain` — towardsdatascience.com → medium cookies
  - `test_get_cookies_for_url_no_session` — returns None when no file
  - `test_get_cookies_for_url_unknown` — non-matching URL → None
  - (No test for `login_interactive` — requires real browser; test the surrounding logic only)

- `tests/test_fetcher.py` additions:
  - `test_fetch_auto_loads_cookies` — verify `get_cookies_for_url` is called when no cookies passed (mock `auth` module)
  - `test_fetch_explicit_cookies_not_overridden` — explicit `--cookies` takes precedence

---

## Verification (Manual)

1. `pip install -e ".[login]" && playwright install chromium`
2. `audio-articles login substack` → browser opens, user logs in → "Session saved" message
3. `audio-articles convert --url https://<paid-post>.substack.com/p/<slug>` → full article, no `--cookies` flag
4. `audio-articles login medium` → browser opens, user logs in → "Session saved" message
5. `audio-articles convert --url https://medium.com/@user/<member-only-article>` → full article
6. `audio-articles convert --url https://towardsdatascience.com/<article>` → full article (custom domain)
7. `audio-articles logout substack` → session deleted; next convert fetches without cookies
8. `audio-articles logout --all` → both sessions deleted
9. Run without playwright installed → clear error message with install instructions
