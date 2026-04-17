from pathlib import Path

import pytest

from audio_articles.core.exceptions import ExtractionError
from audio_articles.core.fetcher import extract_from_file, extract_from_text, fetch_and_extract


def test_extract_from_text_basic():
    result = extract_from_text("Hello world. This is a test article.", title="Test")
    assert result.title == "Test"
    assert result.body == "Hello world. This is a test article."
    assert result.word_count == 7


def test_extract_from_text_default_title():
    result = extract_from_text("Some content here.")
    assert result.title == "Article"


def test_extract_from_file(tmp_path: Path):
    f = tmp_path / "article.txt"
    f.write_text("This is the article body.", encoding="utf-8")
    result = extract_from_file(f)
    assert result.body == "This is the article body."
    assert result.title == "article"  # stem of filename


def test_extract_from_file_with_title(tmp_path: Path):
    f = tmp_path / "article.txt"
    f.write_text("Body text here.", encoding="utf-8")
    result = extract_from_file(f, title="My Title")
    assert result.title == "My Title"


def test_fetch_and_extract_http_error(mocker):
    from curl_cffi.requests.exceptions import HTTPError

    mock_response = mocker.MagicMock(status_code=404)
    mocker.patch(
        "audio_articles.core.fetcher.cffi_requests.get",
        side_effect=HTTPError("404", response=mock_response),
    )

    with pytest.raises(ExtractionError, match="HTTP 404"):
        fetch_and_extract("https://example.com/article")


def test_fetch_and_extract_no_content(mocker):
    mock_response = mocker.MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.text = "<html><body></body></html>"
    mocker.patch("audio_articles.core.fetcher.cffi_requests.get", return_value=mock_response)
    mocker.patch("audio_articles.core.fetcher.trafilatura.extract", return_value=None)

    with pytest.raises(ExtractionError, match="Could not extract"):
        fetch_and_extract("https://example.com/empty")


def test_fetch_auto_loads_cookies_when_none_given(mocker):
    """fetch_and_extract calls _get_saved_cookies when no cookies arg is passed."""
    mocker.patch(
        "audio_articles.core.fetcher._get_saved_cookies",
        return_value=None,
    )
    mock_resp = mocker.MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.text = "<html><body></body></html>"
    mocker.patch("audio_articles.core.fetcher.cffi_requests.get", return_value=mock_resp)
    mocker.patch("audio_articles.core.fetcher.trafilatura.extract", return_value="Body text.")
    mocker.patch(
        "audio_articles.core.fetcher.trafilatura.extract_metadata",
        return_value=mocker.MagicMock(title="Test"),
    )

    fetch_and_extract("https://example.com/article")

    import audio_articles.core.fetcher as fetcher_module
    fetcher_module._get_saved_cookies.assert_called_once_with("https://example.com/article")


def test_fetch_does_not_call_auto_load_when_cookies_given(mocker):
    """Explicit cookies skip the auto-load path entirely."""
    mock_auto = mocker.patch("audio_articles.core.fetcher._get_saved_cookies")
    mock_resp = mocker.MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.text = "<html><body></body></html>"
    mocker.patch("audio_articles.core.fetcher.cffi_requests.get", return_value=mock_resp)
    mocker.patch("audio_articles.core.fetcher.trafilatura.extract", return_value="Body.")
    mocker.patch(
        "audio_articles.core.fetcher.trafilatura.extract_metadata",
        return_value=mocker.MagicMock(title="T"),
    )

    fetch_and_extract("https://example.com/article", cookies={"my": "cookie"})

    mock_auto.assert_not_called()


def test_fetch_passes_saved_cookies_to_http_get(mocker):
    """When auto-load returns cookies, they are passed to the HTTP client."""
    saved = {"substack.sid": "tok123"}
    mocker.patch("audio_articles.core.fetcher._get_saved_cookies", return_value=saved)
    mock_resp = mocker.MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.text = '{"title": "T", "body_html": "<p>Body.</p>", "canonical_url": "https://foo.substack.com/p/article"}'
    mock_get = mocker.patch("audio_articles.core.fetcher.cffi_requests.get", return_value=mock_resp)
    mocker.patch("audio_articles.core.fetcher.trafilatura.extract", return_value="Body.")
    mocker.patch(
        "audio_articles.core.fetcher.trafilatura.extract_metadata",
        return_value=mocker.MagicMock(title="T"),
    )

    fetch_and_extract("https://foo.substack.com/p/article")

    call_kwargs = mock_get.call_args.kwargs
    assert call_kwargs["cookies"] == saved


from audio_articles.core.fetcher import _is_medium_html


def test_is_medium_html_detects_cdn_script():
    html = '<script src="https://cdn-client.medium.com/lite/bundle.js"></script>'
    assert _is_medium_html(html) is True


def test_is_medium_html_detects_og_site_name():
    html = '<meta property="og:site_name" content="Medium"/>'
    assert _is_medium_html(html) is True


def test_is_medium_html_returns_false_for_non_medium():
    html = "<html><body><p>Hello world</p></body></html>"
    assert _is_medium_html(html) is False


def test_fetch_retries_with_medium_cookies_for_unknown_custom_domain(mocker):
    """If HTML has Medium markers and content is short, retries with saved Medium cookies."""
    medium_html = (
        '<script src="https://cdn-client.medium.com/a.js"></script>'
        "<p>Short.</p>"
    )
    full_text = "Full article content. " * 70  # > 200 words

    mocker.patch("audio_articles.core.fetcher._get_saved_cookies", return_value=None)
    mocker.patch(
        "audio_articles.core.fetcher._get_medium_cookies",
        return_value={"uid": "123", "sid": "abc"},
    )

    mock_resp_short = mocker.MagicMock()
    mock_resp_short.raise_for_status.return_value = None
    mock_resp_short.text = medium_html

    mock_resp_full = mocker.MagicMock()
    mock_resp_full.raise_for_status.return_value = None
    mock_resp_full.text = "<html><body><p>" + full_text + "</p></body></html>"

    mocker.patch(
        "audio_articles.core.fetcher.cffi_requests.get",
        side_effect=[mock_resp_short, mock_resp_full],
    )
    mocker.patch(
        "audio_articles.core.fetcher.trafilatura.extract",
        side_effect=["Short.", full_text],
    )
    mocker.patch(
        "audio_articles.core.fetcher.trafilatura.extract_metadata",
        return_value=mocker.MagicMock(title="Article"),
    )

    result = fetch_and_extract("https://unknown-medium-pub.com/article")
    assert result.word_count > 200


def test_fetch_does_not_retry_when_no_medium_session(mocker):
    """If Medium HTML detected but no session saved, no retry occurs."""
    medium_html = '<script src="https://cdn-client.medium.com/a.js"></script><p>Short.</p>'

    mocker.patch("audio_articles.core.fetcher._get_saved_cookies", return_value=None)
    mocker.patch("audio_articles.core.fetcher._get_medium_cookies", return_value=None)

    mock_resp = mocker.MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.text = medium_html
    mock_get = mocker.patch(
        "audio_articles.core.fetcher.cffi_requests.get", return_value=mock_resp
    )
    mocker.patch("audio_articles.core.fetcher.trafilatura.extract", return_value="Short.")
    mocker.patch(
        "audio_articles.core.fetcher.trafilatura.extract_metadata",
        return_value=mocker.MagicMock(title="T"),
    )

    fetch_and_extract("https://unknown-medium-pub.com/article")
    assert mock_get.call_count == 1  # no retry


# ── Playwright 403 fallback ───────────────────────────────────────────────────

def test_fetch_falls_back_to_playwright_on_403_with_session(mocker):
    """When curl_cffi gets 403 and a session exists, retries with headless Playwright."""
    from curl_cffi.requests.exceptions import HTTPError

    full_cookies = [{"name": "uid", "value": "123", "domain": ".medium.com", "path": "/"}]

    mock_response = mocker.MagicMock(status_code=403)
    mocker.patch(
        "audio_articles.core.fetcher.cffi_requests.get",
        side_effect=HTTPError("403", response=mock_response),
    )
    mocker.patch(
        "audio_articles.core.fetcher._get_saved_cookies",
        return_value={"uid": "123"},
    )
    mocker.patch(
        "audio_articles.core.fetcher._get_full_session_cookies",
        return_value=full_cookies,
    )
    mock_playwright_fetch = mocker.patch(
        "audio_articles.core.fetcher._fetch_html_playwright",
        return_value="<html><body><article>Full article body text here.</article></body></html>",
    )
    mocker.patch(
        "audio_articles.core.fetcher.trafilatura.extract",
        return_value="Full article body text here.",
    )
    mocker.patch(
        "audio_articles.core.fetcher.trafilatura.extract_metadata",
        return_value=mocker.MagicMock(title="Article"),
    )

    result = fetch_and_extract("https://medium.com/@user/article")

    mock_playwright_fetch.assert_called_once()
    assert result.body == "Full article body text here."


def test_fetch_does_not_fall_back_to_playwright_without_session(mocker):
    """403 with no saved session re-raises the original error."""
    from curl_cffi.requests.exceptions import HTTPError

    mock_response = mocker.MagicMock(status_code=403)
    mocker.patch(
        "audio_articles.core.fetcher.cffi_requests.get",
        side_effect=HTTPError("403", response=mock_response),
    )
    mocker.patch("audio_articles.core.fetcher._get_saved_cookies", return_value=None)
    mocker.patch("audio_articles.core.fetcher._get_full_session_cookies", return_value=None)

    with pytest.raises(ExtractionError, match="HTTP 403"):
        fetch_and_extract("https://medium.com/@user/article")


def test_fetch_does_not_fall_back_to_playwright_on_non_403(mocker):
    """Non-403 HTTP errors are not retried with Playwright."""
    from curl_cffi.requests.exceptions import HTTPError

    mock_response = mocker.MagicMock(status_code=404)
    mocker.patch(
        "audio_articles.core.fetcher.cffi_requests.get",
        side_effect=HTTPError("404", response=mock_response),
    )
    mocker.patch(
        "audio_articles.core.fetcher._get_full_session_cookies",
        return_value=[{"name": "uid", "value": "x", "domain": ".medium.com", "path": "/"}],
    )
    mock_playwright_fetch = mocker.patch("audio_articles.core.fetcher._fetch_html_playwright")

    with pytest.raises(ExtractionError, match="HTTP 404"):
        fetch_and_extract("https://medium.com/@user/article")

    mock_playwright_fetch.assert_not_called()
