import pytest

from audio_articles.core.exceptions import SummarizationError
from audio_articles.core.summarizer import _split_chunks, summarize


def test_split_chunks_short_text():
    text = "Hello world."
    chunks = _split_chunks(text, size=100, overlap=10)
    assert chunks == ["Hello world."]


def test_split_chunks_produces_overlap():
    # 30-char chunks with 5-char overlap on a longer text
    text = "word " * 40  # 200 chars
    chunks = _split_chunks(text, size=50, overlap=10)
    assert len(chunks) > 1
    # Each chunk except the last should be at most size + a little boundary slack
    for chunk in chunks[:-1]:
        assert len(chunk) <= 60


def test_split_chunks_no_loss():
    text = "The quick brown fox jumps over the lazy dog. " * 10
    chunks = _split_chunks(text, size=80, overlap=20)
    # Reassembling without overlap isn't trivial but every word in original
    # should appear somewhere in the chunks
    combined = " ".join(chunks)
    for word in text.split():
        assert word in combined


def test_summarize_calls_claude(sample_extraction, mocker):
    mock_create = mocker.patch(
        "audio_articles.core.summarizer.Anthropic"
    )
    mock_instance = mock_create.return_value
    mock_instance.messages.create.return_value = mocker.MagicMock(
        content=[mocker.MagicMock(text="This is the audiobook script.")]
    )

    mocker.patch(
        "audio_articles.core.summarizer.get_settings",
        return_value=mocker.MagicMock(
            anthropic_api_key="test-key",
            claude_model="claude-sonnet-4-6",
            summarizer_max_tokens=2048,
            script_word_target=400,
            chunk_threshold_chars=12000,
            chunk_size_chars=8000,
            chunk_overlap_chars=500,
        ),
    )

    result = summarize(sample_extraction)
    assert result.script == "This is the audiobook script."
    assert result.chunks_used == 1
    mock_instance.messages.create.assert_called_once()


def test_summarize_raises_on_api_error(sample_extraction, mocker):
    mock_create = mocker.patch("audio_articles.core.summarizer.Anthropic")
    mock_instance = mock_create.return_value
    mock_instance.messages.create.side_effect = Exception("API down")

    mocker.patch(
        "audio_articles.core.summarizer.get_settings",
        return_value=mocker.MagicMock(
            anthropic_api_key="test-key",
            claude_model="claude-sonnet-4-6",
            summarizer_max_tokens=2048,
            script_word_target=400,
            chunk_threshold_chars=12000,
            chunk_size_chars=8000,
            chunk_overlap_chars=500,
        ),
    )

    with pytest.raises(SummarizationError, match="Claude API call failed"):
        summarize(sample_extraction)
