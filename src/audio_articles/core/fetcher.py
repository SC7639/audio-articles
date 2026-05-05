import json
import re
from pathlib import Path

import trafilatura
from curl_cffi import requests as cffi_requests

from .asset_extractor import extract_assets
from .exceptions import ExtractionError
from .models import ArticleAssets, ExtractionResult

# Matches: https://foo.substack.com/p/some-slug
_SUBSTACK_POST_RE = re.compile(
    r"^(https?://[^/]+\.substack\.com)/p/([^/?#]+)", re.IGNORECASE
)


def load_cookies_file(path: Path) -> dict[str, str]:
    """Parse a Netscape cookie file and return a name→value dict.

    Netscape format (tab-separated):
        domain  include_subdomains  path  secure  expires  name  value
    Lines beginning with '#' are comments.
    """
    cookies: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            name, value = parts[5], parts[6]
            cookies[name] = value
    return cookies


def _get_saved_cookies(url: str) -> dict[str, str] | None:
    """Load saved session cookies for the given URL's platform, if any."""
    from .auth import get_cookies_for_url
    return get_cookies_for_url(url)


# HTML signatures that identify a Medium-hosted page
_MEDIUM_HTML_MARKERS = (
    "cdn-client.medium.com",
    'content="Medium"',
)


def _is_medium_html(html: str) -> bool:
    """Return True if the HTML contains markers that identify a Medium-hosted page."""
    return any(marker in html for marker in _MEDIUM_HTML_MARKERS)


# Cloudflare challenge pages are served as HTTP 200 but contain no article content.
# The challenge script is always loaded from challenges.cloudflare.com.
_CLOUDFLARE_MARKERS = (
    "challenges.cloudflare.com",
    "cf_chl_opt",
)


def _is_cloudflare_challenge(html: str) -> bool:
    """Return True if the response HTML is a Cloudflare bot-detection challenge page."""
    return any(marker in html for marker in _CLOUDFLARE_MARKERS)


def _get_medium_cookies() -> dict[str, str] | None:
    """Load saved Medium session cookies (used for post-fetch custom-domain detection)."""
    from .auth import get_medium_cookies
    return get_medium_cookies()


def _fetch_html_playwright(url: str, *, timeout: float, cookies: list[dict]) -> str:
    """Fetch a page using headless Playwright with saved session cookies.

    Used as a fallback when curl_cffi is blocked by bot detection (403).
    Playwright executes real JavaScript and passes browser fingerprint checks
    that TLS impersonation alone cannot handle.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ExtractionError(
            "Playwright is not installed. Run:\n"
            "  uv sync --extra login\n"
            "  playwright install chromium"
        ) from exc

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        if cookies:
            context.add_cookies(cookies)
        page = context.new_page()
        try:
            page.goto(url, timeout=int(timeout * 1000), wait_until="domcontentloaded")
            content = page.content()
        finally:
            browser.close()
    return content


def _get_full_session_cookies(url: str) -> list[dict] | None:
    """Return the raw cookie list (with domain info) for the platform matching url."""
    from .auth import SessionStore, _platform_for_url
    platform = _platform_for_url(url)
    if platform is None:
        return None
    return SessionStore().load(platform)


def _acquire_raw_html(
    url: str,
    *,
    timeout: float,
    cookies: dict[str, str] | None,
) -> tuple[str, str, str | None]:
    """Fetch raw HTML for an article URL; handle Substack API, 403 + Cloudflare fallback.

    Returns (raw_html, source_url, override_title).
    For Substack URLs, raw_html is the API's body_html, source_url is the canonical
    URL, and override_title is the Substack-supplied title. For other URLs, raw_html
    is the full page HTML, source_url is the input url, and override_title is None
    (trafilatura will infer the title from metadata).
    """
    m = _SUBSTACK_POST_RE.match(url)
    if m:
        base, slug = m.group(1), m.group(2)
        api_url = f"{base}/api/v1/posts/{slug}"
        raw = _fetch_html(api_url, timeout=timeout, cookies=cookies)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ExtractionError(f"Unexpected response from Substack API: {exc}") from exc
        body_html = data.get("body_html") or ""
        if not body_html:
            raise ExtractionError(
                f"No article body returned by Substack API for '{slug}'. "
                "The post may require a paid subscription — pass --cookies with your session."
            )
        title = data.get("title") or slug
        source_url = data.get("canonical_url") or f"{base}/p/{slug}"
        return body_html, source_url, title

    try:
        raw_html = _fetch_html(url, timeout=timeout, cookies=cookies)
    except ExtractionError as exc:
        if "HTTP 403" not in str(exc):
            raise
        full_cookies = _get_full_session_cookies(url)
        if full_cookies is None:
            raise
        raw_html = _fetch_html_playwright(url, timeout=timeout, cookies=full_cookies)

    if _is_cloudflare_challenge(raw_html):
        full_cookies = _get_full_session_cookies(url) or []
        raw_html = _fetch_html_playwright(url, timeout=timeout, cookies=full_cookies)

    return raw_html, url, None


def _maybe_medium_refetch(
    url: str,
    raw_html: str,
    word_count: int,
    cookies: dict[str, str] | None,
    *,
    timeout: float,
) -> tuple[str, dict[str, str] | None]:
    """Re-fetch with saved Medium cookies if the page looks like a paywalled Medium custom domain.

    Returns (possibly-new raw_html, possibly-new cookies). If no re-fetch is needed,
    returns the originals unchanged.
    """
    if cookies is not None or word_count >= 200 or not _is_medium_html(raw_html):
        return raw_html, cookies
    medium_cookies = _get_medium_cookies()
    if medium_cookies is None:
        return raw_html, cookies
    return _fetch_html(url, timeout=timeout, cookies=medium_cookies), medium_cookies


def fetch_and_extract(
    url: str,
    *,
    timeout: float = 20.0,
    cookies: dict[str, str] | None = None,
) -> ExtractionResult:
    """Download the page at `url` and extract main article text via trafilatura.

    Substack post URLs are automatically rewritten to the JSON API endpoint,
    which bypasses Cloudflare bot protection on the reader page.

    If no `cookies` are provided, saved login sessions are loaded automatically
    for Substack and Medium URLs. Unknown Medium custom domains are detected
    post-fetch via HTML markers and retried with saved Medium cookies if available.

    If curl_cffi receives a 403 and there are saved session cookies for the URL's
    platform, the fetch is retried with headless Playwright (which passes JS-based
    bot-detection checks that TLS impersonation cannot).
    """
    _cookies = cookies if cookies is not None else _get_saved_cookies(url)
    raw_html, source_url, override_title = _acquire_raw_html(url, timeout=timeout, cookies=_cookies)
    result = _build_extraction(raw_html, source_url=source_url, override_title=override_title)

    if override_title is None:
        new_html, _ = _maybe_medium_refetch(
            url, raw_html, result.word_count, _cookies, timeout=timeout
        )
        if new_html is not raw_html:
            result = _build_extraction(new_html, source_url=source_url, override_title=None)
    return result


def fetch_with_assets(
    url: str,
    output_dir: Path,
    *,
    timeout: float = 20.0,
    cookies: dict[str, str] | None = None,
) -> tuple[ExtractionResult, ArticleAssets]:
    """Fetch the article and capture companion-PDF assets.

    Like ``fetch_and_extract`` but additionally returns ``ArticleAssets`` (code
    blocks + downloaded images) and substitutes ``(See code block N…)`` /
    ``(See figure N…)`` markers into the extracted body text in place of the
    original structured elements. Both summary and no-summary audio paths
    therefore contain natural references to the PDF.
    """
    _cookies = cookies if cookies is not None else _get_saved_cookies(url)
    raw_html, source_url, override_title = _acquire_raw_html(url, timeout=timeout, cookies=_cookies)

    # Only probe for Medium re-fetch if the heuristic could trigger; avoids a wasted
    # trafilatura run on every non-Medium article.
    if override_title is None and _cookies is None and _is_medium_html(raw_html):
        probe = _build_extraction(raw_html, source_url=source_url, override_title=None)
        raw_html, _cookies = _maybe_medium_refetch(
            url, raw_html, probe.word_count, _cookies, timeout=timeout
        )

    assets, marker_html = extract_assets(
        raw_html, base_url=source_url, output_dir=output_dir, cookies=_cookies
    )
    extraction = _build_extraction(
        marker_html, source_url=source_url, override_title=override_title
    )
    return extraction, assets


def _fetch_substack_api(
    base: str,
    slug: str,
    *,
    timeout: float,
    cookies: dict[str, str] | None,
) -> ExtractionResult:
    """Legacy entry point preserved for tests; delegates through the shared helpers."""
    raw_html, source_url, title = _acquire_raw_html(
        f"{base}/p/{slug}", timeout=timeout, cookies=cookies
    )
    return _build_extraction(raw_html, source_url=source_url, override_title=title)


def extract_from_text(text: str, title: str = "Article") -> ExtractionResult:
    """Wrap raw plain text in an ExtractionResult."""
    words = text.split()
    return ExtractionResult(
        title=title,
        body=text,
        word_count=len(words),
    )


def extract_from_file(path: Path, title: str | None = None) -> ExtractionResult:
    """Read a UTF-8 text file and return an ExtractionResult."""
    text = path.read_text(encoding="utf-8")
    return extract_from_text(text, title=title or path.stem)


def _fetch_html(url: str, *, timeout: float, cookies: dict[str, str] | None = None) -> str:
    try:
        resp = cffi_requests.get(
            url,
            impersonate="chrome124",
            cookies=cookies or {},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.text
    except cffi_requests.exceptions.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "unknown"
        raise ExtractionError(f"HTTP {status} fetching {url}") from exc
    except cffi_requests.exceptions.Timeout as exc:
        raise ExtractionError(f"Timed out fetching {url}") from exc
    except cffi_requests.exceptions.RequestException as exc:
        raise ExtractionError(f"Network error fetching {url}: {exc}") from exc


def _build_extraction(
    raw_html: str, *, source_url: str, override_title: str | None
) -> ExtractionResult:
    """Run trafilatura on (possibly marker-injected) HTML and produce ExtractionResult.

    ``override_title`` short-circuits trafilatura metadata extraction and is used
    for Substack, where the API gives us a clean title and the body_html fragment
    has no <title> for trafilatura to find.
    """
    body = trafilatura.extract(
        raw_html,
        include_comments=False,
        include_tables=False,
        favor_recall=True,
        output_format="txt",
        url=source_url,
    )
    if not body:
        # Fragment fallback: strip tags manually when trafilatura's heuristics give up.
        body = re.sub(r"<[^>]+>", " ", raw_html)
        body = re.sub(r"\s+", " ", body).strip()
    if not body:
        raise ExtractionError(f"Could not extract article content from {source_url}")

    if override_title:
        title = override_title
    else:
        metadata = trafilatura.extract_metadata(raw_html, default_url=source_url)
        title = (metadata.title if metadata and metadata.title else None) or source_url

    return ExtractionResult(
        title=title,
        body=body,
        source_url=source_url,
        word_count=len(body.split()),
    )


def _extract_from_html(raw_html: str, source_url: str) -> ExtractionResult:
    """Backwards-compatible alias preserved for any external callers."""
    return _build_extraction(raw_html, source_url=source_url, override_title=None)
