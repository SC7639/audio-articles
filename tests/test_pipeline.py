import pytest

from audio_articles.core.models import ArticleInput, AudiobookResult
from audio_articles.core.pipeline import run, save_audio


def test_run_with_text(sample_extraction, sample_script, mocker):
    mocker.patch(
        "audio_articles.core.pipeline.extract_from_text",
        return_value=sample_extraction,
    )
    mocker.patch(
        "audio_articles.core.pipeline.summarize",
        return_value=sample_script,
    )
    mocker.patch(
        "audio_articles.core.pipeline.synthesize",
        return_value=b"fake-mp3-bytes",
    )

    article_input = ArticleInput(text="Some article text.")
    result = run(article_input)

    assert isinstance(result, AudiobookResult)
    assert result.audio_bytes == b"fake-mp3-bytes"
    assert result.script == sample_script.script
    assert result.title == sample_extraction.title


def test_run_with_url(sample_extraction, sample_script, mocker):
    mocker.patch(
        "audio_articles.core.pipeline.fetch_and_extract",
        return_value=sample_extraction,
    )
    mocker.patch(
        "audio_articles.core.pipeline.summarize",
        return_value=sample_script,
    )
    mocker.patch(
        "audio_articles.core.pipeline.synthesize",
        return_value=b"fake-mp3-bytes",
    )

    article_input = ArticleInput(url="https://example.com/article")
    result = run(article_input)

    assert result.source_url == "https://example.com/article"
    assert result.audio_bytes == b"fake-mp3-bytes"


def test_save_audio_creates_file(tmp_path, sample_extraction, sample_script):
    result = AudiobookResult(
        audio_bytes=b"fake-mp3",
        script=sample_script.script,
        title="Test Article",
    )
    saved = save_audio(result, output_dir=str(tmp_path))
    assert saved.exists()
    assert saved.suffix == ".mp3"
    assert saved.read_bytes() == b"fake-mp3"


def test_article_input_local_defaults_false():
    inp = ArticleInput(text="Some text.")
    assert inp.local is False


def test_article_input_local_can_be_set():
    inp = ArticleInput(text="Some text.", local=True)
    assert inp.local is True


def test_save_audio_sanitizes_title(tmp_path, sample_script):
    result = AudiobookResult(
        audio_bytes=b"data",
        script=sample_script.script,
        title="Article: 'With Special! Chars?'",
    )
    saved = save_audio(result, output_dir=str(tmp_path))
    assert " " not in saved.name
    assert "'" not in saved.name
    assert "!" not in saved.name
