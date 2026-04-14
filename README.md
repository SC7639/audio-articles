# Audio Articles

Convert any web article into a concise MP3 audiobook using Claude (summarization) and OpenAI TTS (text-to-speech). Ask follow-up questions about the article using Claude Q&A with prompt caching.

## How it works

```
URL or text
    │
    ▼
trafilatura          — extracts clean article text from any webpage
    │
    ▼
Claude (Sonnet)      — rewrites the article as a ~400-word spoken-word script
    │
    ▼
OpenAI tts-1-hd      — converts the script to an MP3 audio file
    │
    ▼
MP3 + Q&A            — download the audio, then ask Claude questions about the article
```

Long articles (> 12,000 characters) are handled with a map-reduce approach: each chunk is summarised independently, then synthesised into a single script. Article Q&A uses Claude's prompt caching so repeated questions on the same article cost ~90% less after the first call (~$0.001/question).

---

## Requirements

- Python 3.11+
- An [Anthropic API key](https://console.anthropic.com/)
- An [OpenAI API key](https://platform.openai.com/api-keys)

---

## Installation

```bash
git clone https://github.com/SC7639/audio-articles.git
cd audio-articles

pip install -e .

cp .env.example .env
```

Open `.env` and fill in your API keys:

```env
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
```

---

## CLI

### Convert an article to audio

```bash
# From a URL
audio-articles convert --url https://example.com/article

# From a local text file
audio-articles convert --file article.txt

# Inline text
audio-articles convert --text "Paste your article here..."
```

### Options

| Flag | Description | Default |
|---|---|---|
| `--output / -o` | Output MP3 path | `./output/<title>.mp3` |
| `--output-dir` | Directory for the MP3 | `./output/` |
| `--voice / -v` | TTS voice (see below) | `onyx` |
| `--title` | Override article title | auto-detected |
| `--script-only` | Print script, skip audio | off |
| `--verbose` | Print script after saving | off |
| `--interactive / -i` | Enter Q&A mode after converting | off |

### Available voices

`alloy` · `echo` · `fable` · `onyx` · `nova` · `shimmer`

```bash
audio-articles convert --url https://example.com/article --voice nova
```

### Preview the script without generating audio

```bash
audio-articles convert --url https://example.com/article --script-only
```

### Interactive Q&A after conversion

```bash
audio-articles convert --url https://example.com/article --interactive
# Saves the MP3, then drops into a Q&A prompt:
# Question: What is the main argument?
# Answer: ...
# Question: exit
```

### One-off question about an article

```bash
audio-articles ask "What are the key takeaways?" --url https://example.com/article
audio-articles ask "Who is quoted?" --file article.txt
```

---

## Web app

```bash
uvicorn audio_articles.web.app:app --reload
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

The web UI lets you:
- Paste a URL or article text
- Choose a voice
- **Preview script** — see the summarised script before generating audio
- **Generate audio** — stream an MP3 directly to the browser
- **Ask questions** — chat with Claude about the article after conversion

### API endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/convert` | Convert to MP3, streams `audio/mpeg` |
| `POST` | `/api/v1/script` | Summarise only, returns JSON script |
| `POST` | `/api/v1/chat` | Ask a question, returns JSON answer |
| `POST` | `/api/v1/convert/upload` | Upload a `.txt` file, streams MP3 |
| `GET` | `/api/v1/voices` | List available voices |
| `GET` | `/api/v1/health` | Health check |
| `GET` | `/docs` | Interactive API docs (Swagger) |

#### Example request

```bash
curl -X POST http://localhost:8000/api/v1/script \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/article"}' | jq .
```

```bash
curl -X POST http://localhost:8000/api/v1/convert \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/article", "voice": "nova"}' \
  --output article.mp3
```

---

## Configuration

All settings can be overridden via environment variables in `.env`:

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Required |
| `OPENAI_API_KEY` | — | Required |
| `CLAUDE_MODEL` | `claude-sonnet-4-6` | Claude model to use |
| `TTS_VOICE` | `onyx` | Default TTS voice |
| `SCRIPT_WORD_TARGET` | `400` | Target word count for the script |
| `SUMMARIZER_MAX_TOKENS` | `2048` | Max tokens for Claude response |
| `OUTPUT_DIR` | `./output` | Default directory for saved MP3s |
| `HOST` | `0.0.0.0` | Web server host |
| `PORT` | `8000` | Web server port |

---

## Project structure

```
src/audio_articles/
├── core/
│   ├── config.py       # Settings (pydantic-settings + .env)
│   ├── exceptions.py   # ExtractionError, SummarizationError, TTSError
│   ├── models.py       # Pydantic models (ArticleInput, AudiobookResult, QATurn, …)
│   ├── fetcher.py      # Article extraction (trafilatura)
│   ├── summarizer.py   # Claude API — article → script (with map-reduce for long articles)
│   ├── tts.py          # OpenAI TTS — script → MP3
│   ├── qa.py           # Claude Q&A with prompt caching
│   └── pipeline.py     # Orchestrates the full flow
├── cli/
│   └── main.py         # Typer CLI (convert + ask commands)
└── web/
    ├── app.py          # FastAPI app factory
    ├── routes.py       # API route handlers
    ├── schemas.py      # Request/response models
    └── static/
        └── index.html  # Single-page web UI
```

---

## Running tests

```bash
pip install -e ".[dev]"
pytest
```

---

## Cost estimates

| Operation | Approximate cost |
|---|---|
| Convert a typical article (800 words) | ~$0.01 |
| Q&A question (after first, with caching) | ~$0.001 |
| TTS for a 400-word script | ~$0.006 |
