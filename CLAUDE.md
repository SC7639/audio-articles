# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`audio-articles` converts web articles (URL, file, or raw text) into MP3 audiobooks using LLMs for summarization and TTS for audio synthesis. It exposes both a Typer CLI and a FastAPI web app backed by the same core pipeline.

## Commands

### Development setup
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env  # then add API keys
```

### Running
```bash
# CLI
audio-articles convert --url https://example.com/article
audio-articles ask "What is the main argument?" --url https://example.com

# Web app
uvicorn audio_articles.web.app:app --reload
# → http://localhost:8000
```

### Tests
```bash
pytest                        # all tests
pytest tests/test_fetcher.py  # single file
pytest -k "test_chunk"        # single test by name
```

### Lint / format
```bash
ruff check .    # lint
ruff format .   # format (line-length=100, py311 target)
```

## Architecture

### Pipeline flow
```
Article input (URL / file / text)
  → fetch & extract  (core/fetcher.py)     trafilatura + curl-cffi
  → summarize        (core/summarizer.py)  Claude API or Ollama
  → synthesize       (core/tts.py)         OpenAI TTS or edge-tts
  → AudiobookResult  (audio bytes + script + metadata)
```

`core/pipeline.py` orchestrates these three stages and is the single entrypoint used by both the CLI and the web routes.

### Source layout
```
src/audio_articles/
  core/        – business logic (fetcher, summarizer, tts, qa, pipeline, models, config)
  cli/         – Typer entry point (main.py)
  web/         – FastAPI app, routes, schemas, static/index.html (single-page UI)
tests/
```

### Dual-mode support
Every stage has a **cloud** path and a **local** path, selected by `ArticleInput.local`:
- Summarization: Claude API (Anthropic SDK) vs. Ollama (OpenAI-compatible endpoint)
- TTS: OpenAI `tts-1-hd` vs. Microsoft `edge-tts`

### Map-reduce for long articles
When an article body exceeds `chunk_threshold_chars` (12 000 chars), `summarizer.py` splits it into 8 000-char chunks with 500-char overlap, summarizes each independently, then merges into a final ~400-word script.

### Prompt caching in Q&A
`core/qa.py` applies `cache_control="ephemeral"` to the article body so that after the first question, subsequent turns cost ~90% less in tokens. Multi-turn history is tracked as a list of `QATurn` objects.

### Substack extraction
`fetcher.py` detects Substack post URLs and rewrites them to the Substack JSON API (`/api/v1/posts/by-slug/…`) to bypass the rendered HTML paywall layer. Other paywalled sites can be handled via the `--cookies` flag (Netscape cookie file).

### Article fetching
`curl-cffi` (not `requests`/`httpx`) is used for HTTP fetching because it impersonates a real Chrome browser fingerprint, bypassing Cloudflare and similar bot-detection systems.

### Web API endpoints
| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/convert` | Stream MP3 audio |
| POST | `/api/v1/script` | Return script preview (JSON) |
| POST | `/api/v1/chat` | Q&A with prompt caching |
| POST | `/api/v1/convert/upload` | File upload + convert |
| GET | `/api/v1/voices` | List available TTS voices |
| GET | `/api/v1/health` | Health check |

Web routes offload blocking pipeline calls to a `ThreadPoolExecutor` (FastAPI's `run_in_executor`) since the core pipeline is synchronous.

## Configuration

All config lives in `core/config.py` (pydantic-settings, loaded from `.env`):

| Variable | Default | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Required for cloud summarization |
| `OPENAI_API_KEY` | — | Required for cloud TTS |
| `CLAUDE_MODEL` | `claude-sonnet-4-6` | |
| `TTS_VOICE` | `onyx` | alloy / echo / fable / onyx / nova / shimmer |
| `SCRIPT_WORD_TARGET` | `400` | Target spoken-word count |
| `OUTPUT_DIR` | `./output` | MP3 save directory |
| `OLLAMA_URL` | `http://localhost:11434/v1` | Local mode |
| `OLLAMA_MODEL` | `llama3.2` | Local mode |
| `EDGE_TTS_VOICE` | `en-GB-RyanNeural` | Local mode TTS voice |

Chunking thresholds (`chunk_threshold_chars`, `chunk_size_chars`, `chunk_overlap_chars`) are hardcoded constants in `config.py`, not env vars.

## Key models (`core/models.py`)

```
ArticleInput      – url | text | title | cookies | local flag
ExtractionResult  – title | body | source_url | word_count
ScriptResult      – script | word_count | chunks_used
AudiobookResult   – audio_bytes | script | title | source_url | format
QATurn            – question | answer (multi-turn history)
```

## Exception hierarchy (`core/exceptions.py`)

```
AudioArticlesError
├── ExtractionError
├── SummarizationError
└── TTSError
```

## Coding conventions

- Python ≥ 3.11; fully type-annotated
- Ruff enforces rules: `E`, `F`, `I` (isort), `UP` (pyupgrade), `B` (bugbear), `SIM`
- Tests use `pytest-asyncio` with `asyncio_mode = "auto"` and `pytest-mock` (`mocker` fixture)
- Patch at the public boundary, not internal privates (e.g. patch `openai.OpenAI`, not `audio_articles.core.tts._client`)
