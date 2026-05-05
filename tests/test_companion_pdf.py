"""Smoke tests for the Playwright PDF renderer.

Skipped automatically when Chromium isn't installed (e.g. CI environments that
don't run ``playwright install chromium``)."""

import pytest

from audio_articles.core.companion_pdf import render_companion_pdf
from audio_articles.core.models import ArticleAssets, CodeBlock


@pytest.fixture(scope="module")
def chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
            return True
    except Exception:
        return False


def test_render_pdf_with_code_block(tmp_path, chromium_available):
    if not chromium_available:
        pytest.skip("Chromium not installed (run: playwright install chromium)")
    assets = ArticleAssets(
        code_blocks=[CodeBlock(content="print('hello world')", language="python")],
        images=[],
    )
    pdf_bytes = render_companion_pdf(
        title="Smoke Test",
        source_url="https://example.com/article",
        assets=assets,
        image_dir=tmp_path,
    )
    assert pdf_bytes.startswith(b"%PDF-")
    assert len(pdf_bytes) > 1000  # a real PDF, not an error stub


def test_render_pdf_handles_unknown_language(tmp_path, chromium_available):
    if not chromium_available:
        pytest.skip("Chromium not installed")
    assets = ArticleAssets(
        code_blocks=[CodeBlock(content="<<>>!@", language="not-a-real-language")],
        images=[],
    )
    pdf_bytes = render_companion_pdf(
        title="Unknown lang",
        source_url=None,
        assets=assets,
        image_dir=tmp_path,
    )
    assert pdf_bytes.startswith(b"%PDF-")
