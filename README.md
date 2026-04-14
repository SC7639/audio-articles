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
- **Cloud mode (default):** An [Anthropic API key](https://console.anthropic.com/) + an [OpenAI API key](https://platform.openai.com/api-keys)
- **Local mode (`--local`):** [Ollama](https://ollama.com/) running locally — no API keys, no cost

---

## Installation

```bash
git clone https://github.com/SC7639/audio-articles.git
cd audio-articles

python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

pip install -e .

cp .env.example .env
```

Open `.env` and fill in your API keys:

```env
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
```

> **Note:** The `-e` (editable) flag means code changes take effect immediately — no reinstall needed after editing source files. Only re-run `pip install -e .` when you add new dependencies to `pyproject.toml`.

### Global install (`audio-articles` on your `PATH`)

To use the CLI from any directory without activating the project virtualenv, install from the repository root using one of these:

**pipx (recommended)** — isolated environment and a single global command:

```bash
python3 -m pip install --user pipx
python3 -m pipx ensurepath   # restart the shell if prompted

cd audio-articles
pipx install -e .
```

After pulling changes that affect dependencies or entry points, run `pipx install -e . --force` from the same directory.

**User install** — installs the launcher into `~/.local/bin` (add that directory to your `PATH` if it is not already):

```bash
cd audio-articles
python3 -m pip install --user -e .
```

Configure API keys the same way as above (`cp .env.example .env` in the repo, or export the variables). This app reads `.env` from your **current working directory** when you run a command, so either export keys in your shell or run from a directory that contains your `.env`.

---

## Dev environment

```bash
# Install with dev dependencies (pytest, ruff, etc.)
pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check .
ruff format .
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
| `--local / -l` | Use Ollama + edge-tts (free, no API keys) | off |
| `--cookies / -c` | Netscape cookie file for paywalled articles | — |

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

### Fetching paywalled / Substack articles

Export your browser cookies as a Netscape cookie file (e.g. with the [Get cookies.txt LOCALLY](https://chrome.google.com/webstore/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) extension) and pass the file with `--cookies`:

```bash
audio-articles convert --url https://yourname.substack.com/p/post-slug --cookies cookies.txt
```

---

## Local mode (free, no API keys)

Use `--local` / `-l` to run everything on your machine using [Ollama](https://ollama.com/) for summarization and Microsoft's [edge-tts](https://github.com/rany2/edge-tts) (the same neural voices as Edge's read-aloud) for TTS. No API keys or billing required.

### Setup

```bash
# 1. Install Ollama
#    macOS/Linux: https://ollama.com/download
#    Windows: download the installer from https://ollama.com/download

# 2. Pull a model (llama3.2 is the default)
ollama pull llama3.2

# 3. Start the Ollama server (it may start automatically on install)
ollama serve
```

### Usage

```bash
audio-articles convert --url https://example.com/article --local
audio-articles convert --file article.txt --local --script-only
```

### Configuration

Override local mode defaults in `.env`:

```env
OLLAMA_MODEL=llama3.2          # any model you've pulled
OLLAMA_URL=http://localhost:11434/v1
EDGE_TTS_VOICE=en-GB-RyanNeural  # any voice from: edge-tts --list
```

List all available edge-tts voices:

```bash
edge-tts --list
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
| `ANTHROPIC_API_KEY` | — | Required for cloud mode |
| `OPENAI_API_KEY` | — | Required for cloud mode |
| `CLAUDE_MODEL` | `claude-sonnet-4-6` | Claude model to use |
| `TTS_VOICE` | `onyx` | Default TTS voice (cloud mode) |
| `SCRIPT_WORD_TARGET` | `400` | Target word count for the script |
| `SUMMARIZER_MAX_TOKENS` | `2048` | Max tokens for summarizer response |
| `OUTPUT_DIR` | `./output` | Default directory for saved MP3s |
| `HOST` | `0.0.0.0` | Web server host |
| `PORT` | `8000` | Web server port |
| `OLLAMA_URL` | `http://localhost:11434/v1` | Ollama API endpoint (local mode) |
| `OLLAMA_MODEL` | `llama3.2` | Ollama model to use (local mode) |
| `EDGE_TTS_VOICE` | `en-GB-RyanNeural` | edge-tts voice (local mode) |

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

## Cost estimates

| Operation | Approximate cost |
|---|---|
| Convert a typical article (800 words) | ~$0.01 |
| Q&A question (after first, with caching) | ~$0.001 |
| TTS for a 400-word script | ~$0.006 |
