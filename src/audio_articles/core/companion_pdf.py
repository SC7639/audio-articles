"""Render an article's companion PDF via headless Chromium (Playwright).

The HTML doc is written to a temp file inside ``image_dir`` so that relative
``<img src="image_001.png">`` references resolve via ``file://`` — this is the
only way Playwright will inline the downloaded images into the resulting PDF.
"""

from __future__ import annotations

import html
import logging
from pathlib import Path

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name, guess_lexer
from pygments.util import ClassNotFound

from .models import ArticleAssets

_LOG = logging.getLogger(__name__)


class CompanionPdfError(Exception):
    """Raised when the PDF render fails (e.g. Playwright not installed)."""


_BASE_CSS = """
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         max-width: 720px; margin: 1em auto; padding: 0 1em; line-height: 1.4; }
  h1 { margin-top: 0; }
  h2 { margin-top: 1.6em; border-bottom: 1px solid #ddd; padding-bottom: 0.2em; }
  h3 { margin-top: 1.2em; font-size: 1.05em; color: #333; }
  .source { color: #666; font-size: 0.9em; }
  pre { overflow-x: auto; padding: 0.75em; border-radius: 4px; background: #f6f8fa; }
  pre code, code { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 0.85em; }
  figure { margin: 1.5em 0; page-break-inside: avoid; }
  figure img { max-width: 100%; height: auto; }
  figcaption { font-size: 0.85em; color: #666; margin-top: 0.4em; text-align: center; }
  .highlight { padding: 0; border-radius: 4px; overflow-x: auto; }
"""


def render_companion_pdf(
    *,
    title: str,
    source_url: str | None,
    assets: ArticleAssets,
    image_dir: Path,
) -> bytes:
    """Build an HTML doc and render it to PDF bytes via headless Chromium.

    ``image_dir`` is the directory where ``extract_assets`` downloaded images.
    A temporary HTML file is written into the same directory so relative ``<img>``
    paths resolve. The HTML file is cleaned up before return; the caller owns
    cleanup of the image files themselves.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise CompanionPdfError(
            "Playwright is required for companion PDF rendering. Install it via:\n"
            "  uv sync --extra login   (or: pip install -e '.[login]')\n"
            "  playwright install chromium"
        ) from exc

    formatter = HtmlFormatter(style="default", noclasses=True)
    inline_css = formatter.get_style_defs(".highlight")
    full_html = _build_html(
        title=title,
        source_url=source_url,
        assets=assets,
        inline_css=inline_css,
        formatter=formatter,
    )

    image_dir.mkdir(parents=True, exist_ok=True)
    html_file = image_dir / "_companion.html"
    html_file.write_text(full_html, encoding="utf-8")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_context().new_page()
                page.goto(f"file://{html_file.resolve()}", wait_until="load")
                pdf_bytes = page.pdf(
                    format="A4",
                    print_background=True,
                    margin={"top": "1.5cm", "right": "1.5cm", "bottom": "1.5cm", "left": "1.5cm"},
                )
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001 — surface Playwright errors as CompanionPdfError
        raise CompanionPdfError(f"Chromium PDF render failed: {exc}") from exc
    finally:
        html_file.unlink(missing_ok=True)

    return pdf_bytes


def _build_html(
    *,
    title: str,
    source_url: str | None,
    assets: ArticleAssets,
    inline_css: str,
    formatter: HtmlFormatter,
) -> str:
    parts: list[str] = []
    parts.append(f"<h1>{html.escape(title)}</h1>")
    if source_url:
        escaped = html.escape(source_url)
        parts.append(f'<p class="source">Source: <a href="{escaped}">{escaped}</a></p>')

    if assets.code_blocks:
        parts.append("<h2>Code blocks</h2>")
        for i, block in enumerate(assets.code_blocks, start=1):
            heading = f"Code block {i}"
            if block.language:
                heading += f" — {html.escape(block.language)}"
            parts.append(f"<h3>{heading}</h3>")
            parts.append(_highlight_code(block.content, block.language, formatter))

    if assets.images:
        parts.append("<h2>Figures</h2>")
        for i, asset in enumerate(assets.images, start=1):
            parts.append("<figure>")
            parts.append(f"<h3>Figure {i}</h3>")
            src_attr = html.escape(asset.local_filename)
            alt_attr = html.escape(asset.alt_text or "")
            parts.append(f'<img src="{src_attr}" alt="{alt_attr}" />')
            caption = asset.caption or asset.alt_text
            if caption:
                parts.append(f"<figcaption>{html.escape(caption)}</figcaption>")
            parts.append("</figure>")

    body = "\n".join(parts)
    style = _BASE_CSS + "\n" + inline_css
    return (
        "<!DOCTYPE html>\n"
        '<html><head><meta charset="utf-8">'
        f"<title>{html.escape(title)}</title>"
        f"<style>{style}</style>"
        f"</head><body>\n{body}\n</body></html>"
    )


def _highlight_code(content: str, language: str | None, formatter: HtmlFormatter) -> str:
    """Pygments-highlight the given code, falling back to plain <pre> if no lexer matches."""
    lexer = None
    if language:
        try:
            lexer = get_lexer_by_name(language, stripall=False)
        except ClassNotFound:
            lexer = None
    if lexer is None:
        try:
            lexer = guess_lexer(content)
        except ClassNotFound:
            return f"<pre><code>{html.escape(content)}</code></pre>"
    return highlight(content, lexer, formatter)
