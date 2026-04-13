import re

from anthropic import Anthropic

from .config import get_settings
from .exceptions import SummarizationError
from .models import ExtractionResult, ScriptResult

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert audiobook narrator and editor. Your job is to transform article \
text into a spoken-word script that is concise, clear, and engaging to listen to.

Rules:
- Target approximately {word_target} words for the final script.
- Write in full, flowing sentences — no bullet points, no headers, no markdown.
- Preserve the core argument and the most compelling evidence or examples.
- Open with a hook sentence that names the topic and why it matters.
- Close with the article's main takeaway or call-to-action.
- Use natural spoken transitions ("What's more,", "Here's why that matters:", etc.).
- Do not add information that is not in the source article.
- Return ONLY the script text, with no preamble or metadata."""

_CHUNK_SUMMARY_SYSTEM = "You are a precise summarizer. Condense the given text into its most important points using plain prose sentences."

_CHUNK_SUMMARY_USER = """\
Summarize the following portion of an article into the 5 to 8 most important points. \
Use full prose sentences, not bullet points. Be concise.

{chunk}"""

_REDUCE_USER = """\
You have been given a series of section summaries from an article titled "{title}". \
Synthesize them into a single, cohesive audiobook script of approximately {word_target} words. \
Follow the output rules in your system prompt.

{summaries}"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def summarize(extraction: ExtractionResult) -> ScriptResult:
    """Convert an ExtractionResult into a ScriptResult using the Claude API."""
    settings = get_settings()
    client = Anthropic(api_key=settings.anthropic_api_key)

    body = extraction.body

    if len(body) <= settings.chunk_threshold_chars:
        script = _single_call(client, body, extraction.title, settings)
        return ScriptResult(script=script, word_count=len(script.split()), chunks_used=1)

    # Long article: map → reduce
    chunks = _split_chunks(body, settings.chunk_size_chars, settings.chunk_overlap_chars)
    summaries = [_chunk_summary(client, chunk, settings) for chunk in chunks]
    combined = "\n\n---\n\n".join(
        f"Section {i + 1}:\n{s}" for i, s in enumerate(summaries)
    )
    script = _reduce_call(client, combined, extraction.title, settings)
    return ScriptResult(
        script=script,
        word_count=len(script.split()),
        chunks_used=len(chunks),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _single_call(client: Anthropic, body: str, title: str, settings) -> str:
    system = _SYSTEM_PROMPT.format(word_target=settings.script_word_target)
    user_msg = f'Article title: "{title}"\n\nArticle text:\n{body}'
    return _call_claude(client, system, user_msg, settings)


def _chunk_summary(client: Anthropic, chunk: str, settings) -> str:
    user_msg = _CHUNK_SUMMARY_USER.format(chunk=chunk)
    return _call_claude(client, _CHUNK_SUMMARY_SYSTEM, user_msg, settings, max_tokens=512)


def _reduce_call(client: Anthropic, summaries: str, title: str, settings) -> str:
    system = _SYSTEM_PROMPT.format(word_target=settings.script_word_target)
    user_msg = _REDUCE_USER.format(
        title=title,
        word_target=settings.script_word_target,
        summaries=summaries,
    )
    return _call_claude(client, system, user_msg, settings)


def _call_claude(
    client: Anthropic,
    system: str,
    user_msg: str,
    settings,
    max_tokens: int | None = None,
) -> str:
    try:
        response = client.messages.create(
            model=settings.claude_model,
            max_tokens=max_tokens or settings.summarizer_max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )
    except Exception as exc:
        raise SummarizationError(f"Claude API call failed: {exc}") from exc

    if not response.content:
        raise SummarizationError("Claude returned an empty response.")

    return response.content[0].text.strip()


def _split_chunks(text: str, size: int, overlap: int) -> list[str]:
    """Split text into overlapping character-level chunks, breaking on whitespace."""
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            # Extend to the next whitespace so we don't cut mid-word
            ws = text.find(" ", end)
            if ws != -1 and ws - end < 200:
                end = ws
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap
    return chunks
