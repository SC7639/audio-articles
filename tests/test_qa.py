import pytest

from audio_articles.core.exceptions import SummarizationError
from audio_articles.core.models import QATurn
from audio_articles.core.qa import ask


def test_ask_calls_claude(sample_extraction, mocker):
    mock_anthropic = mocker.patch("audio_articles.core.qa.Anthropic")
    mock_instance = mock_anthropic.return_value
    mock_instance.messages.create.return_value = mocker.MagicMock(
        content=[mocker.MagicMock(text="Renewables will supply half of global electricity by 2030.")]
    )
    mocker.patch(
        "audio_articles.core.qa.get_settings",
        return_value=mocker.MagicMock(
            anthropic_api_key="test-key",
            claude_model="claude-sonnet-4-6",
        ),
    )

    answer = ask("What is the key prediction?", sample_extraction)

    assert answer == "Renewables will supply half of global electricity by 2030."
    mock_instance.messages.create.assert_called_once()


def test_ask_passes_history(sample_extraction, mocker):
    mock_anthropic = mocker.patch("audio_articles.core.qa.Anthropic")
    mock_instance = mock_anthropic.return_value
    mock_instance.messages.create.return_value = mocker.MagicMock(
        content=[mocker.MagicMock(text="Solar and wind.")]
    )
    mocker.patch(
        "audio_articles.core.qa.get_settings",
        return_value=mocker.MagicMock(
            anthropic_api_key="test-key",
            claude_model="claude-sonnet-4-6",
        ),
    )

    history = [QATurn(question="First question?", answer="First answer.")]
    ask("Second question?", sample_extraction, history=history)

    call_kwargs = mock_instance.messages.create.call_args
    messages = call_kwargs.kwargs["messages"]
    # Should have: prior user, prior assistant, new user = 3 messages
    assert len(messages) == 3
    assert messages[0] == {"role": "user", "content": "First question?"}
    assert messages[1] == {"role": "assistant", "content": "First answer."}
    assert messages[2]["role"] == "user"
    assert messages[2]["content"] == "Second question?"


def test_ask_uses_cache_control(sample_extraction, mocker):
    mock_anthropic = mocker.patch("audio_articles.core.qa.Anthropic")
    mock_instance = mock_anthropic.return_value
    mock_instance.messages.create.return_value = mocker.MagicMock(
        content=[mocker.MagicMock(text="Answer.")]
    )
    mocker.patch(
        "audio_articles.core.qa.get_settings",
        return_value=mocker.MagicMock(
            anthropic_api_key="test-key",
            claude_model="claude-sonnet-4-6",
        ),
    )

    ask("Any question?", sample_extraction)

    call_kwargs = mock_instance.messages.create.call_args
    system = call_kwargs.kwargs["system"]
    # System must be a list of content blocks, with the article block having cache_control
    assert isinstance(system, list)
    article_block = next(b for b in system if "Article text" in b.get("text", ""))
    assert article_block.get("cache_control") == {"type": "ephemeral"}


def test_ask_raises_on_api_error(sample_extraction, mocker):
    mock_anthropic = mocker.patch("audio_articles.core.qa.Anthropic")
    mock_instance = mock_anthropic.return_value
    mock_instance.messages.create.side_effect = Exception("API unavailable")
    mocker.patch(
        "audio_articles.core.qa.get_settings",
        return_value=mocker.MagicMock(
            anthropic_api_key="test-key",
            claude_model="claude-sonnet-4-6",
        ),
    )

    with pytest.raises(SummarizationError, match="Claude Q&A call failed"):
        ask("Any question?", sample_extraction)


def test_ask_raises_on_empty_response(sample_extraction, mocker):
    mock_anthropic = mocker.patch("audio_articles.core.qa.Anthropic")
    mock_instance = mock_anthropic.return_value
    mock_instance.messages.create.return_value = mocker.MagicMock(content=[])
    mocker.patch(
        "audio_articles.core.qa.get_settings",
        return_value=mocker.MagicMock(
            anthropic_api_key="test-key",
            claude_model="claude-sonnet-4-6",
        ),
    )

    with pytest.raises(SummarizationError, match="empty response"):
        ask("Any question?", sample_extraction)
