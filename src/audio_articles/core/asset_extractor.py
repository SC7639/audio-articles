"""Parse raw article HTML into companion-PDF assets and inject reference markers.

The marker injection rewrites each ``<pre>``, ``<img>``, ``<figure>``, and inline
``<svg>`` element into a ``<p>(See code block N in the companion PDF.)`` (or
``figure N``) sentence. After trafilatura extracts text, those sentences survive
as natural prose so the audio script — both summarized and full-text paths —
narrates references the listener can flip to in the PDF.
"""

from __future__ import annotations

import base64
import io
import logging
import re
import urllib.parse
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from bs4.element import Tag
from curl_cffi import requests as cffi_requests
from PIL import Image, UnidentifiedImageError

from .models import ArticleAssets, CodeBlock, ImageAsset

_MIN_IMAGE_DIM = 200  # px — below this, treat as decorative (avatars, tracking pixels)
_FETCH_TIMEOUT = 20.0
_LOG = logging.getLogger(__name__)


def extract_assets(
    raw_html: str,
    *,
    base_url: str | None,
    output_dir: Path,
    cookies: dict[str, str] | None = None,
) -> tuple[ArticleAssets, str]:
    """Parse HTML, capture code blocks + images, return (assets, marker-injected HTML)."""
    soup = BeautifulSoup(raw_html, "html.parser")
    output_dir.mkdir(parents=True, exist_ok=True)

    code_blocks: list[CodeBlock] = []
    images: list[ImageAsset] = []

    for pre in soup.find_all("pre"):
        content = pre.get_text("\n", strip=True)
        if not content:
            continue
        code_blocks.append(CodeBlock(content=content, language=_detect_language(pre)))
        _replace_with_marker(soup, pre, "code block", len(code_blocks))

    for fig in soup.find_all("figure"):
        asset = _figure_to_asset(fig, base_url, output_dir, len(images) + 1, cookies)
        if asset is None:
            fig.decompose()
            continue
        images.append(asset)
        _replace_with_marker(soup, fig, "figure", len(images))

    for img in soup.find_all("img"):
        asset = _img_to_asset(img, base_url, output_dir, len(images) + 1, cookies, caption=None)
        if asset is None:
            img.decompose()
            continue
        images.append(asset)
        _replace_with_marker(soup, img, "figure", len(images))

    for svg in soup.find_all("svg"):
        if not _svg_is_meaningful(svg):
            svg.decompose()
            continue
        filename = _save_svg(svg, output_dir, len(images) + 1)
        images.append(ImageAsset(local_filename=filename, is_svg=True))
        _replace_with_marker(soup, svg, "figure", len(images))

    return ArticleAssets(code_blocks=code_blocks, images=images), str(soup)


def _replace_with_marker(soup: BeautifulSoup, element: Tag, kind: str, idx: int) -> None:
    marker = soup.new_tag("p")
    marker.string = f"(See {kind} {idx} in the companion PDF.)"
    element.replace_with(marker)


def _detect_language(pre: Tag) -> str | None:
    """Read a `language-x` / `lang-x` class hint off the <pre> or its inner <code>."""
    code = pre.find("code") or pre
    classes = code.get("class") or []
    for cls in classes:
        for prefix in ("language-", "lang-"):
            if cls.startswith(prefix):
                return cls[len(prefix):]
    return None


def _figure_to_asset(
    fig: Tag,
    base_url: str | None,
    output_dir: Path,
    idx: int,
    cookies: dict[str, str] | None,
) -> ImageAsset | None:
    """Pick the most content-bearing element inside a <figure>.

    Substack and similar editors wrap each image in a <figure> that also contains
    20×20 <svg> toolbar icons (expand, share). The <img> is always the real
    content; <svg> is only meaningful when it's the *only* graphic in the figure
    AND it's not a tiny icon.
    """
    caption_el = fig.find("figcaption")
    caption = caption_el.get_text(strip=True) if caption_el else None
    img = fig.find("img")
    if img is not None:
        return _img_to_asset(img, base_url, output_dir, idx, cookies, caption=caption)
    svg = fig.find("svg")
    if svg is not None and _svg_is_meaningful(svg):
        filename = _save_svg(svg, output_dir, idx)
        return ImageAsset(local_filename=filename, caption=caption, is_svg=True)
    return None


def _svg_is_meaningful(svg: Tag) -> bool:
    """Filter out tiny toolbar/icon SVGs (e.g. 20×20 share buttons) from being
    treated as figures. Only filters when both width and height are present and
    parseable; SVGs without explicit dimensions are kept (assumed to be diagrams)."""
    width = svg.get("width")
    height = svg.get("height")
    if width is None or height is None:
        return True
    try:
        w = int(re.match(r"\d+", str(width)).group())
        h = int(re.match(r"\d+", str(height)).group())
    except (AttributeError, ValueError):
        return True
    return w >= _MIN_IMAGE_DIM or h >= _MIN_IMAGE_DIM


def _img_to_asset(
    img: Tag,
    base_url: str | None,
    output_dir: Path,
    idx: int,
    cookies: dict[str, str] | None,
    *,
    caption: str | None,
) -> ImageAsset | None:
    src = img.get("src") or img.get("data-src") or img.get("data-original")
    if not src:
        return None
    alt = img.get("alt") or None
    full_url = _resolve_url(src, base_url)
    raw_bytes = _fetch_image_bytes(full_url, cookies)
    if raw_bytes is None:
        return None
    try:
        with Image.open(io.BytesIO(raw_bytes)) as pil:
            width, height = pil.size
            fmt = (pil.format or "PNG").lower()
    except (UnidentifiedImageError, OSError):
        return None
    if width < _MIN_IMAGE_DIM and height < _MIN_IMAGE_DIM:
        return None
    ext = "jpg" if fmt == "jpeg" else fmt
    filename = f"image_{idx:03d}.{ext}"
    (output_dir / filename).write_bytes(raw_bytes)
    return ImageAsset(local_filename=filename, alt_text=alt, caption=caption, is_svg=False)


def _save_svg(svg: Tag, output_dir: Path, idx: int) -> str:
    filename = f"image_{idx:03d}.svg"
    (output_dir / filename).write_text(str(svg), encoding="utf-8")
    return filename


def _resolve_url(src: str, base_url: str | None) -> str:
    if src.startswith("data:"):
        return src
    if src.startswith("//"):
        return "https:" + src
    if base_url:
        return urljoin(base_url, src)
    return src


def _fetch_image_bytes(url: str, cookies: dict[str, str] | None) -> bytes | None:
    if url.startswith("data:"):
        return _decode_data_uri(url)
    try:
        resp = cffi_requests.get(
            url,
            impersonate="chrome124",
            cookies=cookies or {},
            timeout=_FETCH_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.content
    except Exception as exc:  # noqa: BLE001 — best-effort image fetch
        _LOG.debug("Image fetch failed for %s: %s", url, exc)
        return None


def _decode_data_uri(uri: str) -> bytes | None:
    m = re.match(r"data:([^;,]+)?(;base64)?,(.*)", uri, re.DOTALL)
    if not m:
        return None
    payload = m.group(3)
    is_base64 = m.group(2) == ";base64"
    try:
        if is_base64:
            return base64.b64decode(payload)
        return urllib.parse.unquote_to_bytes(payload)
    except (ValueError, base64.binascii.Error):
        return None
