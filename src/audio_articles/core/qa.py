"""Article Q&A using Claude with prompt caching.

The article body is marked with cache_control="ephemeral" so Claude's API
caches it after the first call — subsequent questions about the same article
only pay for the question + answer tokens (~90% cost reduction).
"""

from anthropic import Anthropic

from .config import get_settings
from .exceptions import SummarizationError
from .models import ExtractionResult, QATurn

_SYSTEM_INSTRUCTIONS = (
    "You are a helpful assistant answering questions about a specific article. "
    "Answer only based on what the article says. "
    "If the answer is not in the article, clearly state that."
)


def ask(
    question: str,
    extraction: ExtractionResult,
    history: list[QATurn] | None = None,
) -> str:
    """Ask a question about an article and return Claude's answer.

    Args:
        question: The question to ask.
        extraction: The extracted article text used as context.
        history: Prior Q&A turns for multi-turn conversation support.

    Returns:
        Claude's answer as a plain string.
    """
    settings = get_settings()
    client = Anthropic(api_key=settings.anthropic_api_key)

    # The system prompt is a list of content blocks so we can mark the article
    # body with cache_control, caching it across calls for the same article.
    system = [
        {
            "type": "text",
            "text": _SYSTEM_INSTRUCTIONS,
        },
        {
            "type": "text",
            "text": f'Article title: "{extraction.title}"\n\nArticle text:\n{extraction.body}',
            "cache_control": {"type": "ephemeral"},
        },
    ]

    messages: list[dict] = []
    for turn in history or []:
        messages.append({"role": "user", "content": turn.question})
        messages.append({"role": "assistant", "content": turn.answer})
    messages.append({"role": "user", "content": question})

    try:
        response = client.messages.create(
            model=settings.claude_model,
            max_tokens=1024,
            system=system,
            messages=messages,
        )
    except Exception as exc:
        raise SummarizationError(f"Claude Q&A call failed: {exc}") from exc

    if not response.content:
        raise SummarizationError("Claude returned an empty response.")

    return response.content[0].text.strip()
