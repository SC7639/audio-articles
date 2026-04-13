from pathlib import Path

import httpx
import trafilatura

from .exceptions import ExtractionError
from .models import ExtractionResult

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; audio-articles/1.0)"}


def fetch_and_extract(url: str, *, timeout: float = 20.0) -> ExtractionResult:
    """Download the page at `url` and extract main article text via trafilatura."""
    raw_html = _fetch_html(url, timeout=timeout)
    return _extract_from_html(raw_html, source_url=url)


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


def _fetch_html(url: str, *, timeout: float) -> str:
    try:
        resp = httpx.get(url, headers=_HEADERS, timeout=timeout, follow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except httpx.HTTPStatusError as exc:
        raise ExtractionError(f"HTTP {exc.response.status_code} fetching {url}") from exc
    except httpx.TimeoutException as exc:
        raise ExtractionError(f"Timed out fetching {url}") from exc
    except httpx.RequestError as exc:
        raise ExtractionError(f"Network error fetching {url}: {exc}") from exc


def _extract_from_html(raw_html: str, source_url: str) -> ExtractionResult:
    # trafilatura returns a Document object when output_format="xml" or with_metadata=True,
    # but returns a plain string for output_format="txt" without metadata.
    # We call twice: once for metadata, once for clean text.
    metadata = trafilatura.extract_metadata(raw_html, default_url=source_url)
    body = trafilatura.extract(
        raw_html,
        include_comments=False,
        include_tables=False,
        favor_recall=True,
        output_format="txt",
        url=source_url,
    )

    if not body:
        raise ExtractionError(f"Could not extract article content from {source_url}")

    title = (metadata.title if metadata and metadata.title else None) or source_url
    return ExtractionResult(
        title=title,
        body=body,
        source_url=source_url,
        word_count=len(body.split()),
    )
