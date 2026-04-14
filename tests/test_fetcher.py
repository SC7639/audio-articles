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
