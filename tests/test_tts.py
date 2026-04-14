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
