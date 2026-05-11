import pytest

from audio_articles.core.exceptions import TTSError
from audio_articles.core.models import ScriptResult
from audio_articles.core.tts import synthesize


@pytest.fixture
def sample_script_result():
    return ScriptResult(script="This is a test script.", word_count=5, chunks_used=1)


def test_synthesize_local_calls_edge(sample_script_result, mocker):
    """synthesize(local=True) should delegate to _synthesize_edge, not OpenAI."""
    mock_edge = mocker.patch(
        "audio_articles.core.tts._synthesize_edge",
        return_value=b"fake-mp3-local",
    )

    result = synthesize(sample_script_result, local=True)

    assert result == b"fake-mp3-local"
    mock_edge.assert_called_once_with(sample_script_result.script)


def test_synthesize_local_does_not_call_openai(sample_script_result, mocker):
    """synthesize(local=True) must not touch OpenAI at all."""
    mocker.patch("audio_articles.core.tts._synthesize_edge", return_value=b"audio")
    mock_openai = mocker.patch("audio_articles.core.tts.OpenAI")

    synthesize(sample_script_result, local=True)

    mock_openai.assert_not_called()


def test_synthesize_edge_chunks_long_scripts(mocker):
    """A script over the edge-tts word limit must be split into multiple calls
    and the MP3 byte streams concatenated, so the audio is not truncated."""
    from audio_articles.core.tts import _EDGE_WORD_LIMIT, _synthesize_edge

    long_script = " ".join(["word."] * (_EDGE_WORD_LIMIT * 3))  # 3 chunks worth
    mock_call = mocker.patch(
        "audio_articles.core.tts._edge_call",
        side_effect=[b"AAA", b"BBB", b"CCC"],
    )
    mocker.patch(
        "audio_articles.core.tts.get_settings",
        return_value=mocker.MagicMock(edge_tts_voice="en-GB-RyanNeural"),
    )

    result = _synthesize_edge(long_script)

    assert mock_call.call_count == 3
    assert result == b"AAABBBCCC"


def test_synthesize_edge_short_script_single_call(mocker):
    """A script under the limit must not be split (no concatenation overhead)."""
    from audio_articles.core.tts import _synthesize_edge

    mock_call = mocker.patch(
        "audio_articles.core.tts._edge_call",
        return_value=b"audio",
    )
    mocker.patch(
        "audio_articles.core.tts.get_settings",
        return_value=mocker.MagicMock(edge_tts_voice="en-GB-RyanNeural"),
    )

    result = _synthesize_edge("Short script. Just a few words.")

    assert mock_call.call_count == 1
    assert result == b"audio"


def test_synthesize_cloud_calls_openai(sample_script_result, mocker):
    """synthesize(local=False) should use the OpenAI TTS path."""
    mocker.patch(
        "audio_articles.core.tts.get_settings",
        return_value=mocker.MagicMock(openai_api_key="key", tts_voice="onyx"),
    )
    mock_client = mocker.MagicMock()
    mock_client.audio.speech.create.return_value.read.return_value = b"cloud-mp3"
    mocker.patch("audio_articles.core.tts.OpenAI", return_value=mock_client)

    result = synthesize(sample_script_result, local=False)

    assert result == b"cloud-mp3"
    mock_client.audio.speech.create.assert_called_once()
