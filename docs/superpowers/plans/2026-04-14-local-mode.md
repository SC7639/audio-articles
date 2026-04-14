# Local Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `--local` flag to the CLI that replaces Claude + OpenAI TTS with Ollama + edge-tts, enabling free development without API credits.

**Architecture:** A `local: bool` field on `ArticleInput` flows from CLI → pipeline → summarizer/tts. Each backend module gains a local path alongside the existing cloud path. No new files — local and cloud live side-by-side in the same modules.

**Tech Stack:** `edge-tts>=6.1` (new dep), `openai` client reused for Ollama (base_url override), `asyncio.run()` to bridge async edge-tts into the sync pipeline.

---

## File Map

| File | Change |
|---|---|
| `pyproject.toml` | Add `edge-tts>=6.1` dependency |
| `src/audio_articles/core/config.py` | Add `ollama_url`, `ollama_model`, `edge_tts_voice` settings |
| `src/audio_articles/core/models.py` | Add `local: bool = False` to `ArticleInput` |
| `src/audio_articles/core/tts.py` | Add `local` param + `_synthesize_edge()` |
| `src/audio_articles/core/summarizer.py` | Add `local` param + `_call_ollama()` |
| `src/audio_articles/core/pipeline.py` | Pass `article_input.local` to summarize/synthesize |
| `src/audio_articles/cli/main.py` | Add `--local/-l` flag to `convert` and `ask` |
| `tests/test_tts.py` | Add local TTS test |
| `tests/test_summarizer.py` | Add local summarizer test |

---

### Task 1: Add edge-tts dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add edge-tts to dependencies**

In `pyproject.toml`, add to the `dependencies` list:

```toml
dependencies = [
    "anthropic>=0.25",
    "openai>=1.30",
    "trafilatura>=1.9",
    "fastapi>=0.111",
    "uvicorn[standard]>=0.29",
    "typer>=0.12",
    "rich>=13.7",
    "pydantic>=2.7",
    "pydantic-settings>=2.2",
    "python-dotenv>=1.0",
    "httpx>=0.27",
    "curl-cffi>=0.7",
    "edge-tts>=6.1",
]
```

- [ ] **Step 2: Install it**

```bash
pip install -e ".[dev]"
```

Expected: `Successfully installed edge-tts-...`

- [ ] **Step 3: Verify import works**

```bash
python3 -c "import edge_tts; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add edge-tts dependency for local TTS mode"
```

---

### Task 2: Add local config settings

**Files:**
- Modify: `src/audio_articles/core/config.py`

- [ ] **Step 1: Add the three new settings to the Settings class**

In `src/audio_articles/core/config.py`, add after `chunk_overlap_chars`:

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    anthropic_api_key: str = ""
    openai_api_key: str = ""

    claude_model: str = "claude-sonnet-4-6"
    tts_voice: str = "onyx"
    summarizer_max_tokens: int = 2048
    script_word_target: int = 400

    # Long-article chunking thresholds (characters)
    chunk_threshold_chars: int = 12_000
    chunk_size_chars: int = 8_000
    chunk_overlap_chars: int = 500

    # Local mode (Ollama + edge-tts)
    ollama_url: str = "http://localhost:11434/v1"
    ollama_model: str = "llama3.2"
    edge_tts_voice: str = "en-GB-RyanNeural"

    host: str = "0.0.0.0"
    port: int = 8000
    output_dir: str = "./output"
```

- [ ] **Step 2: Verify settings load without errors**

```bash
python3 -c "from audio_articles.core.config import get_settings; s = get_settings(); print(s.ollama_model, s.edge_tts_voice)"
```

Expected: `llama3.2 en-GB-RyanNeural`

Note: if `get_settings()` is cached from a previous import, restart the Python process.

- [ ] **Step 3: Commit**

```bash
git add src/audio_articles/core/config.py
git commit -m "feat: add ollama and edge-tts config settings"
```

---

### Task 3: Add `local` field to ArticleInput

**Files:**
- Modify: `src/audio_articles/core/models.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_pipeline.py`:

```python
def test_article_input_local_defaults_false():
    from audio_articles.core.models import ArticleInput
    inp = ArticleInput(url="https://example.com")
    assert inp.local is False


def test_article_input_local_can_be_set():
    from audio_articles.core.models import ArticleInput
    inp = ArticleInput(url="https://example.com", local=True)
    assert inp.local is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_pipeline.py::test_article_input_local_defaults_false -v
```

Expected: FAIL — `ArticleInput` has no field `local`

- [ ] **Step 3: Add `local` to ArticleInput**

In `src/audio_articles/core/models.py`, update `ArticleInput`:

```python
class ArticleInput(BaseModel):
    """Input to the pipeline — exactly one of url or text must be provided."""

    url: HttpUrl | None = None
    text: str | None = None
    title: str | None = None
    cookies: dict[str, str] | None = None
    local: bool = False

    @model_validator(mode="after")
    def _require_source(self) -> "ArticleInput":
        if self.url is None and self.text is None:
            raise ValueError("Provide either 'url' or 'text'.")
        return self
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_pipeline.py -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/audio_articles/core/models.py tests/test_pipeline.py
git commit -m "feat: add local field to ArticleInput"
```

---

### Task 4: Add local TTS via edge-tts

**Files:**
- Modify: `src/audio_articles/core/tts.py`
- Modify: `tests/test_tts.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_tts.py`:

```python
def test_synthesize_local(mocker):
    from audio_articles.core.models import ScriptResult
    from audio_articles.core.tts import synthesize

    fake_audio = b"fake-mp3-bytes"
    mocker.patch(
        "audio_articles.core.tts._synthesize_edge",
        return_value=fake_audio,
    )

    result = synthesize(ScriptResult(script="Hello world.", word_count=2), local=True)
    assert result == fake_audio
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_tts.py::test_synthesize_local -v
```

Expected: FAIL — `synthesize()` has no `local` parameter

- [ ] **Step 3: Add local TTS path to tts.py**

Replace the contents of `src/audio_articles/core/tts.py` with:

```python
import asyncio
import re

import edge_tts
from openai import OpenAI

from .config import get_settings
from .exceptions import TTSError
from .models import ScriptResult

# OpenAI TTS supports roughly 4096 tokens (~3000 words) per request.
_WORD_LIMIT = 2800


def synthesize(script_result: ScriptResult, *, local: bool = False) -> bytes:
    """Convert a ScriptResult to MP3 audio bytes.

    When local=True, uses edge-tts (free, no API key required).
    When local=False, uses OpenAI tts-1-hd.
    """
    if local:
        return _synthesize_edge(script_result.script)

    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)
    script = script_result.script

    words = script.split()
    if len(words) <= _WORD_LIMIT:
        return _single_tts(client, script, settings)

    segments = _split_at_sentences(script, _WORD_LIMIT)
    parts = [_single_tts(client, seg, settings) for seg in segments]
    return b"".join(parts)


def _synthesize_edge(text: str) -> bytes:
    """Synthesize speech using edge-tts (Microsoft neural voices, free)."""
    settings = get_settings()
    voice = settings.edge_tts_voice

    async def _run() -> bytes:
        communicate = edge_tts.Communicate(text, voice)
        chunks: list[bytes] = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])
        return b"".join(chunks)

    try:
        return asyncio.run(_run())
    except Exception as exc:
        raise TTSError(f"edge-tts failed: {exc}") from exc


def _single_tts(client: OpenAI, text: str, settings) -> bytes:
    try:
        response = client.audio.speech.create(
            model="tts-1-hd",
            voice=settings.tts_voice,
            input=text,
            response_format="mp3",
        )
        return response.read()
    except Exception as exc:
        raise TTSError(f"OpenAI TTS call failed: {exc}") from exc


def _split_at_sentences(script: str, word_limit: int) -> list[str]:
    """Split script into segments of at most `word_limit` words, breaking at sentence ends."""
    sentences = re.split(r"(?<=[.!?])\s+", script)
    segments: list[str] = []
    current: list[str] = []
    count = 0
    for sentence in sentences:
        w = len(sentence.split())
        if count + w > word_limit and current:
            segments.append(" ".join(current))
            current = [sentence]
            count = w
        else:
            current.append(sentence)
            count += w
    if current:
        segments.append(" ".join(current))
    return segments
```

- [ ] **Step 4: Run all TTS tests**

```bash
pytest tests/test_tts.py -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/audio_articles/core/tts.py tests/test_tts.py
git commit -m "feat: add local TTS via edge-tts"
```

---

### Task 5: Add local summarizer via Ollama

**Files:**
- Modify: `src/audio_articles/core/summarizer.py`
- Modify: `tests/test_summarizer.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_summarizer.py`:

```python
def test_summarize_local(mocker):
    from audio_articles.core.models import ExtractionResult
    from audio_articles.core.summarizer import summarize

    mock_client = mocker.MagicMock()
    mock_client.chat.completions.create.return_value = mocker.MagicMock(
        choices=[mocker.MagicMock(message=mocker.MagicMock(content="Local script output."))]
    )
    mocker.patch("audio_articles.core.summarizer.OpenAI", return_value=mock_client)

    extraction = ExtractionResult(title="Test", body="Some article text.", word_count=3)
    result = summarize(extraction, local=True)

    assert result.script == "Local script output."
    # Verify it used the ollama base_url
    call_kwargs = mocker.patch("audio_articles.core.summarizer.OpenAI").call_args
    assert "base_url" in call_kwargs.kwargs or (
        call_kwargs.args and "localhost:11434" in str(call_kwargs)
    )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_summarizer.py::test_summarize_local -v
```

Expected: FAIL — `summarize()` has no `local` parameter

- [ ] **Step 3: Add local summarizer path to summarizer.py**

Replace the contents of `src/audio_articles/core/summarizer.py` with:

```python
import re

from anthropic import Anthropic
from openai import APIConnectionError, OpenAI

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


def summarize(extraction: ExtractionResult, *, local: bool = False) -> ScriptResult:
    """Convert an ExtractionResult into a ScriptResult.

    When local=True, uses Ollama (llama3.2 by default) via OpenAI-compatible API.
    When local=False, uses the Anthropic Claude API.
    """
    settings = get_settings()
    body = extraction.body

    if local:
        client = _ollama_client(settings)
        if len(body) <= settings.chunk_threshold_chars:
            script = _single_call_llm(client, body, extraction.title, settings)
        else:
            chunks = _split_chunks(body, settings.chunk_size_chars, settings.chunk_overlap_chars)
            summaries = [_chunk_summary_llm(client, chunk, settings) for chunk in chunks]
            combined = "\n\n---\n\n".join(
                f"Section {i + 1}:\n{s}" for i, s in enumerate(summaries)
            )
            script = _reduce_call_llm(client, combined, extraction.title, settings)
        return ScriptResult(script=script, word_count=len(script.split()), chunks_used=1)

    client = Anthropic(api_key=settings.anthropic_api_key)

    if len(body) <= settings.chunk_threshold_chars:
        script = _single_call(client, body, extraction.title, settings)
        return ScriptResult(script=script, word_count=len(script.split()), chunks_used=1)

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
# Ollama (local) helpers
# ---------------------------------------------------------------------------


def _ollama_client(settings) -> OpenAI:
    return OpenAI(base_url=settings.ollama_url, api_key="ollama")


def _call_llm(client: OpenAI, system: str, user_msg: str, settings, max_tokens: int | None = None) -> str:
    try:
        response = client.chat.completions.create(
            model=settings.ollama_model,
            max_tokens=max_tokens or settings.summarizer_max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg},
            ],
        )
    except APIConnectionError as exc:
        raise SummarizationError(
            f"Ollama not reachable at {settings.ollama_url} — is it running? Try: ollama serve"
        ) from exc
    except Exception as exc:
        raise SummarizationError(f"Ollama call failed: {exc}") from exc

    content = response.choices[0].message.content
    if not content:
        raise SummarizationError("Ollama returned an empty response.")
    return content.strip()


def _single_call_llm(client: OpenAI, body: str, title: str, settings) -> str:
    system = _SYSTEM_PROMPT.format(word_target=settings.script_word_target)
    user_msg = f'Article title: "{title}"\n\nArticle text:\n{body}'
    return _call_llm(client, system, user_msg, settings)


def _chunk_summary_llm(client: OpenAI, chunk: str, settings) -> str:
    user_msg = _CHUNK_SUMMARY_USER.format(chunk=chunk)
    return _call_llm(client, _CHUNK_SUMMARY_SYSTEM, user_msg, settings, max_tokens=512)


def _reduce_call_llm(client: OpenAI, summaries: str, title: str, settings) -> str:
    system = _SYSTEM_PROMPT.format(word_target=settings.script_word_target)
    user_msg = _REDUCE_USER.format(
        title=title,
        word_target=settings.script_word_target,
        summaries=summaries,
    )
    return _call_llm(client, system, user_msg, settings)


# ---------------------------------------------------------------------------
# Claude (cloud) helpers
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


# ---------------------------------------------------------------------------
# Shared chunking
# ---------------------------------------------------------------------------


def _split_chunks(text: str, size: int, overlap: int) -> list[str]:
    """Split text into overlapping character-level chunks, breaking on whitespace."""
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            ws = text.find(" ", end)
            if ws != -1 and ws - end < 200:
                end = ws
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap
    return chunks
```

- [ ] **Step 4: Run all summarizer tests**

```bash
pytest tests/test_summarizer.py -v
```

Expected: all pass (existing tests patch `_call_claude` which is unchanged)

- [ ] **Step 5: Commit**

```bash
git add src/audio_articles/core/summarizer.py tests/test_summarizer.py
git commit -m "feat: add local summarizer via Ollama"
```

---

### Task 6: Thread `local` through the pipeline

**Files:**
- Modify: `src/audio_articles/core/pipeline.py`

- [ ] **Step 1: Update pipeline to pass local flag**

Replace `src/audio_articles/core/pipeline.py` with:

```python
import re
from pathlib import Path

from .config import get_settings
from .fetcher import extract_from_file, extract_from_text, fetch_and_extract
from .models import ArticleInput, AudiobookResult, ExtractionResult
from .summarizer import summarize
from .tts import synthesize


def run_full(article_input: ArticleInput) -> tuple[AudiobookResult, ExtractionResult]:
    """Full pipeline returning both the audiobook result and the extraction."""
    if article_input.url:
        extraction = fetch_and_extract(str(article_input.url), cookies=article_input.cookies)
        if article_input.title:
            extraction = extraction.model_copy(update={"title": article_input.title})
    else:
        text = article_input.text or ""
        extraction = extract_from_text(text, title=article_input.title or "Article")

    script_result = summarize(extraction, local=article_input.local)
    audio_bytes = synthesize(script_result, local=article_input.local)

    result = AudiobookResult(
        audio_bytes=audio_bytes,
        script=script_result.script,
        title=extraction.title,
        source_url=str(article_input.url) if article_input.url else None,
    )
    return result, extraction


def run(article_input: ArticleInput) -> AudiobookResult:
    """Full pipeline: input → extract → summarize → TTS → AudiobookResult."""
    result, _ = run_full(article_input)
    return result


def run_full_from_file(
    path: Path, title: str | None = None
) -> tuple[AudiobookResult, ExtractionResult]:
    """Convenience wrapper for files, returning both audiobook and extraction."""
    extraction = extract_from_file(path, title=title)
    script_result = summarize(extraction)
    audio_bytes = synthesize(script_result)
    result = AudiobookResult(
        audio_bytes=audio_bytes,
        script=script_result.script,
        title=extraction.title,
    )
    return result, extraction


def run_from_file(path: Path, title: str | None = None) -> AudiobookResult:
    """Convenience wrapper that reads a file and runs the full pipeline."""
    result, _ = run_full_from_file(path, title=title)
    return result


def save_audio(result: AudiobookResult, output_dir: str | None = None) -> Path:
    """Write MP3 bytes to disk. Returns the file path written."""
    settings = get_settings()
    out = Path(output_dir or settings.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    safe_title = re.sub(r"[^\w\-]", "_", result.title)[:60]
    path = out / f"{safe_title}.mp3"
    path.write_bytes(result.audio_bytes)
    return path
```

- [ ] **Step 2: Run full test suite**

```bash
pytest -v
```

Expected: all 20+ tests pass

- [ ] **Step 3: Commit**

```bash
git add src/audio_articles/core/pipeline.py
git commit -m "feat: thread local flag through pipeline"
```

---

### Task 7: Add `--local` flag to CLI

**Files:**
- Modify: `src/audio_articles/cli/main.py`

- [ ] **Step 1: Add `--local` to the `convert` command**

In `src/audio_articles/cli/main.py`, add `local` to the `convert` signature after `interactive`:

```python
@app.command()
def convert(
    url: Annotated[str | None, typer.Option("--url", "-u", help="URL of the article to fetch.")] = None,
    file: Annotated[Path | None, typer.Option("--file", "-f", help="Path to a plain-text file.")] = None,
    text: Annotated[str | None, typer.Option("--text", "-t", help="Raw article text (inline).")] = None,
    title: Annotated[str | None, typer.Option("--title", help="Override the article title.")] = None,
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Output MP3 file path.")] = None,
    output_dir: Annotated[str | None, typer.Option("--output-dir", help="Directory to save the output MP3.")] = None,
    voice: VoiceOption = None,
    script_only: Annotated[bool, typer.Option("--script-only", help="Print the script without generating audio.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Print the script after conversion.")] = False,
    interactive: Annotated[bool, typer.Option("--interactive", "-i", help="After converting, enter interactive Q&A mode.")] = False,
    cookies: Annotated[Path | None, typer.Option("--cookies", "-c", help="Netscape cookie file for authenticated fetching.")] = None,
    local: Annotated[bool, typer.Option("--local", "-l", help="Use local Ollama + edge-tts instead of Claude + OpenAI (free, no API keys needed).")] = False,
) -> None:
```

Then update `ArticleInput` construction in the `convert` body (find the line with `ArticleInput(url=url, text=text, title=title, cookies=loaded_cookies)` and add `local=local`):

```python
article_input = ArticleInput(url=url, text=text, title=title, cookies=loaded_cookies, local=local)
```

- [ ] **Step 2: Add `--local` to the `ask` command**

Add `local` to the `ask` signature after `cookies`:

```python
    local: Annotated[bool, typer.Option("--local", "-l", help="Use local Ollama instead of Claude (free, no API key needed).")] = False,
```

Then in the `ask` body, find `extraction = fetch_and_extract(url, cookies=loaded_cookies)` and add `local` to the `qa_ask` call:

```python
        answer = qa_ask(question, extraction, history=history)
```

becomes (pass `local` to the summarizer indirectly — `qa.py` uses Claude directly, so just note this is future work and leave qa.py unchanged for now).

Actually, leave `qa.py` unchanged — it always uses Claude. Local mode for Q&A can be a follow-up. Just add the flag to `ask` as a no-op with a note:

```python
    local: Annotated[bool, typer.Option("--local", "-l", help="(Reserved) Local mode for Q&A is not yet supported.")] = False,
```

- [ ] **Step 3: Run the full test suite**

```bash
pytest -v
```

Expected: all tests pass

- [ ] **Step 4: Smoke test the --local flag is visible**

```bash
audio-articles convert --help
```

Expected: `--local` / `-l` appears in the options list.

- [ ] **Step 5: Commit**

```bash
git add src/audio_articles/cli/main.py
git commit -m "feat: add --local/-l flag to convert and ask commands"
```

---

### Task 8: Update README with local mode setup

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a Local Mode section after the Configuration table**

Add this section to `README.md`:

````markdown
## Local mode (free, no API keys)

Run the full pipeline without Anthropic or OpenAI credits using Ollama + edge-tts.

### Setup

```bash
# 1. Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# 2. Pull a model (llama3.2 is the default, ~2GB)
ollama pull llama3.2

# 3. Ollama starts automatically — verify it's running
ollama list
```

### Usage

```bash
audio-articles convert --url https://example.com/article --local
audio-articles convert --file article.txt --local --script-only
```

### Local config (optional)

Override defaults in `.env`:

```env
OLLAMA_URL=http://localhost:11434/v1
OLLAMA_MODEL=llama3.2
EDGE_TTS_VOICE=en-GB-RyanNeural
```

Available edge-tts voices: `en-GB-RyanNeural` · `en-US-GuyNeural` · `en-AU-WilliamNeural` · `en-IE-ConnorNeural`
````

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add local mode setup and usage to README"
```
