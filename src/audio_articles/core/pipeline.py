import re
from pathlib import Path

from .config import get_settings
from .fetcher import extract_from_file, extract_from_text, fetch_and_extract
from .models import ArticleInput, AudiobookResult
from .summarizer import summarize
from .tts import synthesize


def run(article_input: ArticleInput) -> AudiobookResult:
    """
    Full pipeline: input → extract → summarize → TTS → AudiobookResult.

    This is the single entry point shared by the CLI and web frontends.
    It is deliberately synchronous so the CLI can call it directly without
    an event loop. The web layer runs it in a ThreadPoolExecutor.
    """
    if article_input.url:
        extraction = fetch_and_extract(str(article_input.url))
        if article_input.title:
            extraction = extraction.model_copy(update={"title": article_input.title})
    else:
        text = article_input.text or ""
        extraction = extract_from_text(text, title=article_input.title or "Article")

    script_result = summarize(extraction)
    audio_bytes = synthesize(script_result)

    return AudiobookResult(
        audio_bytes=audio_bytes,
        script=script_result.script,
        title=extraction.title,
        source_url=str(article_input.url) if article_input.url else None,
    )


def run_from_file(path: Path, title: str | None = None) -> AudiobookResult:
    """Convenience wrapper that reads a file and runs the full pipeline."""
    extraction = extract_from_file(path, title=title)
    script_result = summarize(extraction)
    audio_bytes = synthesize(script_result)
    return AudiobookResult(
        audio_bytes=audio_bytes,
        script=script_result.script,
        title=extraction.title,
    )


def save_audio(result: AudiobookResult, output_dir: str | None = None) -> Path:
    """Write MP3 bytes to disk. Returns the file path written."""
    settings = get_settings()
    out = Path(output_dir or settings.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    safe_title = re.sub(r"[^\w\-]", "_", result.title)[:60]
    path = out / f"{safe_title}.mp3"
    path.write_bytes(result.audio_bytes)
    return path
