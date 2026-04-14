# Local Mode Design

**Date:** 2026-04-14  
**Status:** Approved  
**Stack:** Ollama (LLM) + edge-tts (TTS)

## Problem

Anthropic and OpenAI are pay-as-you-go. During development, the developer needs a free path to exercise the full pipeline without incurring API costs.

## Solution

A `--local` flag on the CLI that swaps both paid backends for free local alternatives:

| Service | Cloud | Local |
|---|---|---|
| Summarization | Claude via Anthropic API | Ollama (llama3.2) via OpenAI-compatible API |
| TTS | OpenAI tts-1-hd | edge-tts (Microsoft neural voices, free) |

## Architecture

```
CLI --local
    │
    ▼
pipeline.run(article_input, local=True)
    │
    ├─ summarize(extraction, local=True)
    │       └─ openai client, base_url=http://localhost:11434/v1
    │          model=ollama_model (default: llama3.2)
    │
    └─ synthesize(script_result, local=True)
            └─ edge-tts Communicate → MP3 bytes
               same AudiobookResult shape, format="mp3"
```

## Components

### config.py
Add three new optional settings (all have defaults, no `.env` changes required):
- `ollama_url: str = "http://localhost:11434/v1"`
- `ollama_model: str = "llama3.2"`
- `edge_tts_voice: str = "en-GB-RyanNeural"`

### summarizer.py
Add a `local: bool = False` parameter to `summarize()`. When `True`, construct an `openai.OpenAI` client with `base_url=ollama_url` and `api_key="ollama"` and call `_call_llm()` instead of `_call_claude()`. The prompt templates are reused unchanged — Ollama speaks the same chat completion format.

### tts.py
Add a `local: bool = False` parameter to `synthesize()`. When `True`, call `_synthesize_edge()` which uses `edge_tts.Communicate` to stream audio. edge-tts is async; we run it with `asyncio.run()` since the pipeline is synchronous. Output is MP3 bytes — same contract as the OpenAI path.

### pipeline.py
- `ArticleInput` gains `local: bool = False`
- `run()` and `run_full()` read `article_input.local` and pass it to `summarize()` and `synthesize()`

### cli/main.py
- `convert` and `ask` commands gain `--local / -l` flag
- When set, `ArticleInput(local=True)` (convert) or direct `local=True` kwarg (ask)

### pyproject.toml
- Add `edge-tts>=6.1` to `[project.dependencies]`

## Setup (user-facing)

```bash
# 1. Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# 2. Pull a model
ollama pull llama3.2

# 3. Run (Ollama starts automatically on most installs)
audio-articles convert --url https://... --local
```

## Error Handling

- If Ollama is not running: `openai.APIConnectionError` → caught, re-raised as `SummarizationError` with message "Ollama not reachable at {url} — is it running?"
- If edge-tts fails: re-raised as `TTSError`

## Testing

- Existing mocks in `test_summarizer.py` / `test_tts.py` patch at the `_call_claude` / `_single_tts` level — no changes needed
- Add two new tests: `test_summarize_local` (mock openai client with local base_url) and `test_synthesize_local` (mock edge-tts Communicate)
