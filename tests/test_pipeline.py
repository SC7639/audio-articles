from pathlib import Path

from audio_articles.core.models import (
    ArticleAssets,
    ArticleInput,
    AudiobookResult,
    CodeBlock,
)
from audio_articles.core.pipeline import (
    run,
    save_audio,
    save_companion_pdf,
    save_manifest_for,
)


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
    assert result.companion_pdf_bytes is None  # text input never produces a PDF


def test_run_with_url_no_companion_pdf(sample_extraction, sample_script, mocker):
    """companion_pdf=False uses the legacy fast path through fetch_and_extract."""
    mocker.patch(
        "audio_articles.core.pipeline.fetch_and_extract",
        return_value=sample_extraction,
    )
    fetch_with_assets_mock = mocker.patch(
        "audio_articles.core.pipeline.fetch_with_assets"
    )
    mocker.patch(
        "audio_articles.core.pipeline.summarize",
        return_value=sample_script,
    )
    mocker.patch(
        "audio_articles.core.pipeline.synthesize",
        return_value=b"fake-mp3-bytes",
    )

    article_input = ArticleInput(
        url="https://example.com/article", companion_pdf=False
    )
    result = run(article_input)

    assert result.source_url == "https://example.com/article"
    assert result.audio_bytes == b"fake-mp3-bytes"
    assert result.companion_pdf_bytes is None
    fetch_with_assets_mock.assert_not_called()


def test_run_with_url_companion_pdf_renders_when_assets_present(
    sample_extraction, sample_script, mocker
):
    """When companion_pdf=True and assets are non-empty, a PDF is rendered and embedded."""
    assets = ArticleAssets(
        code_blocks=[CodeBlock(content="print('hi')", language="python")],
        images=[],
    )
    mocker.patch(
        "audio_articles.core.pipeline.fetch_with_assets",
        return_value=(sample_extraction, assets),
    )
    render_mock = mocker.patch(
        "audio_articles.core.pipeline.render_companion_pdf",
        return_value=b"%PDF-fake",
    )
    mocker.patch(
        "audio_articles.core.pipeline.summarize",
        return_value=sample_script,
    )
    mocker.patch(
        "audio_articles.core.pipeline.synthesize",
        return_value=b"fake-mp3-bytes",
    )

    result = run(ArticleInput(url="https://example.com/article", companion_pdf=True))

    assert result.companion_pdf_bytes == b"%PDF-fake"
    render_mock.assert_called_once()


def test_run_with_url_companion_pdf_skips_when_no_assets(
    sample_extraction, sample_script, mocker
):
    """No code or images → no PDF rendered, companion_pdf_bytes stays None."""
    mocker.patch(
        "audio_articles.core.pipeline.fetch_with_assets",
        return_value=(sample_extraction, ArticleAssets()),
    )
    render_mock = mocker.patch(
        "audio_articles.core.pipeline.render_companion_pdf",
        return_value=b"%PDF-should-not-be-called",
    )
    mocker.patch(
        "audio_articles.core.pipeline.summarize",
        return_value=sample_script,
    )
    mocker.patch(
        "audio_articles.core.pipeline.synthesize",
        return_value=b"fake-mp3-bytes",
    )

    result = run(ArticleInput(url="https://example.com/article", companion_pdf=True))

    assert result.companion_pdf_bytes is None
    render_mock.assert_not_called()


def test_run_with_pdf_render_failure_degrades(
    sample_extraction, sample_script, mocker
):
    """If the PDF render raises CompanionPdfError, the audio still succeeds and PDF is None."""
    from audio_articles.core.companion_pdf import CompanionPdfError

    assets = ArticleAssets(
        code_blocks=[CodeBlock(content="x")],
        images=[],
    )
    mocker.patch(
        "audio_articles.core.pipeline.fetch_with_assets",
        return_value=(sample_extraction, assets),
    )
    mocker.patch(
        "audio_articles.core.pipeline.render_companion_pdf",
        side_effect=CompanionPdfError("Chromium unavailable"),
    )
    mocker.patch(
        "audio_articles.core.pipeline.summarize",
        return_value=sample_script,
    )
    mocker.patch(
        "audio_articles.core.pipeline.synthesize",
        return_value=b"fake-mp3-bytes",
    )

    result = run(ArticleInput(url="https://example.com/article", companion_pdf=True))

    assert result.audio_bytes == b"fake-mp3-bytes"
    assert result.companion_pdf_bytes is None


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


def test_save_companion_pdf_creates_file(tmp_path, sample_script):
    result = AudiobookResult(
        audio_bytes=b"audio",
        script=sample_script.script,
        title="Test Article",
        companion_pdf_bytes=b"%PDF-fake",
    )
    pdf_path = save_companion_pdf(result, output_dir=str(tmp_path))
    assert pdf_path is not None
    assert pdf_path.exists()
    assert pdf_path.suffix == ".pdf"
    assert pdf_path.read_bytes() == b"%PDF-fake"


def test_save_companion_pdf_returns_none_when_no_bytes(tmp_path, sample_script):
    result = AudiobookResult(
        audio_bytes=b"audio",
        script=sample_script.script,
        title="Test Article",
        companion_pdf_bytes=None,
    )
    assert save_companion_pdf(result, output_dir=str(tmp_path)) is None


def test_save_manifest_writes_sidecar(tmp_path, sample_extraction, sample_script):
    result = AudiobookResult(
        audio_bytes=b"audio",
        script=sample_script.script,
        title="The Future of Renewable Energy",
        source_url="https://example.com/renewables",
    )
    audio_path = Path(tmp_path) / "The_Future_of_Renewable_Energy.mp3"
    audio_path.write_bytes(b"audio")
    pdf_path = Path(tmp_path) / "The_Future_of_Renewable_Energy.pdf"
    pdf_path.write_bytes(b"%PDF")

    manifest_path = save_manifest_for(
        result, sample_extraction, audio_path, pdf_path, output_dir=str(tmp_path)
    )
    assert manifest_path.exists()
    content = manifest_path.read_text()
    assert "The_Future_of_Renewable_Energy.mp3" in content
    assert "The_Future_of_Renewable_Energy.pdf" in content
    assert "https://example.com/renewables" in content


def test_article_input_local_defaults_false():
    inp = ArticleInput(text="Some text.")
    assert inp.local is False


def test_article_input_companion_pdf_defaults_true():
    inp = ArticleInput(text="Some text.")
    assert inp.companion_pdf is True


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
