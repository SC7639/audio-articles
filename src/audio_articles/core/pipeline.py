import logging
import re
import shutil
import tempfile
import threading
from pathlib import Path

from .companion_pdf import CompanionPdfError, render_companion_pdf
from .config import get_settings
from .fetcher import (
    extract_from_file,
    extract_from_text,
    fetch_and_extract,
    fetch_with_assets,
)
from .manifest import ArticleManifest, now_iso, write_manifest
from .models import (
    ArticleInput,
    AudiobookResult,
    ExtractionResult,
    ScriptResult,
)
from .summarizer import summarize
from .tts import synthesize

_LOG = logging.getLogger(__name__)


def safe_stem(title: str) -> str:
    """Compute the disk-safe stem used for both `<title>.mp3` and `<title>.pdf`."""
    return re.sub(r"[^\w\-]", "_", title)[:60]


def unique_stem(
    title: str,
    output_dir: str | Path,
    reserved: set[Path],
    lock: threading.Lock,
) -> str:
    """Pick a stem that won't collide with existing or already-reserved MP3 paths.

    Reserves `<output_dir>/<stem>.mp3` in `reserved` so concurrent callers won't
    pick the same path. Append `_2`, `_3`, … on collision. Caller is responsible
    for sharing the same `reserved` set and `lock` across workers in a batch.
    """
    out = Path(output_dir)
    base = safe_stem(title) or "audio"
    with lock:
        candidate = base
        path = out / f"{candidate}.mp3"
        i = 2
        while path.exists() or path in reserved:
            candidate = f"{base}_{i}"
            path = out / f"{candidate}.mp3"
            i += 1
        reserved.add(path)
    return candidate


def run_full(article_input: ArticleInput) -> tuple[AudiobookResult, ExtractionResult]:
    """Full pipeline returning both the audiobook result and the extraction.

    When ``article_input.companion_pdf`` is True and a URL is provided, also extracts
    code blocks and diagrams from the source article, injects ``(See code block N…)``
    references into the audio script, and renders a companion PDF. The PDF bytes
    ride along on ``AudiobookResult.companion_pdf_bytes``.
    """
    extraction, pdf_bytes = fetch_and_maybe_render_pdf(article_input)

    local = article_input.local
    if article_input.no_summary:
        script_result = ScriptResult(
            script=extraction.body,
            word_count=extraction.word_count,
            chunks_used=1,
        )
    else:
        script_result = summarize(extraction, local=local)
    audio_bytes = synthesize(script_result, local=local)

    result = AudiobookResult(
        audio_bytes=audio_bytes,
        script=script_result.script,
        title=extraction.title,
        source_url=str(article_input.url) if article_input.url else None,
        companion_pdf_bytes=pdf_bytes,
    )
    return result, extraction


def fetch_and_maybe_render_pdf(
    article_input: ArticleInput,
) -> tuple[ExtractionResult, bytes | None]:
    """Drive the extraction phase and render the companion PDF when applicable.

    Exposed publicly so the SSE-streaming web route can yield a status update
    after the fetch+render step but before summarization begins.

    Three paths:
      * text/file input → no HTML, no PDF.
      * URL input + companion_pdf=False → use the legacy fast path (no asset fork).
      * URL input + companion_pdf=True → use ``fetch_with_assets``; if any
        code blocks or images were captured, render the PDF.
    """
    if not article_input.url:
        text = article_input.text or ""
        extraction = extract_from_text(text, title=article_input.title or "Article")
        return extraction, None

    url_str = str(article_input.url)

    if not article_input.companion_pdf:
        extraction = fetch_and_extract(url_str, cookies=article_input.cookies)
        if article_input.title:
            extraction = extraction.model_copy(update={"title": article_input.title})
        return extraction, None

    image_dir = Path(tempfile.mkdtemp(prefix="audio-articles-pdf-"))
    try:
        extraction, assets = fetch_with_assets(
            url_str,
            image_dir,
            cookies=article_input.cookies,
        )
        if article_input.title:
            extraction = extraction.model_copy(update={"title": article_input.title})
        if assets.is_empty:
            return extraction, None
        try:
            pdf_bytes = render_companion_pdf(
                title=extraction.title,
                source_url=extraction.source_url,
                assets=assets,
                image_dir=image_dir,
            )
        except CompanionPdfError as exc:
            _LOG.warning("Companion PDF render skipped: %s", exc)
            return extraction, None
        return extraction, pdf_bytes
    finally:
        shutil.rmtree(image_dir, ignore_errors=True)


def run(article_input: ArticleInput) -> AudiobookResult:
    """
    Full pipeline: input → extract → summarize → TTS → AudiobookResult.

    This is the single entry point shared by the CLI and web frontends.
    It is deliberately synchronous so the CLI can call it directly without
    an event loop. The web layer runs it in a ThreadPoolExecutor.
    """
    result, _ = run_full(article_input)
    return result


def run_full_from_file(
    path: Path, title: str | None = None, no_summary: bool = False
) -> tuple[AudiobookResult, ExtractionResult]:
    """Convenience wrapper for files, returning both audiobook and extraction."""
    extraction = extract_from_file(path, title=title)
    if no_summary:
        script_result = ScriptResult(
            script=extraction.body,
            word_count=extraction.word_count,
            chunks_used=1,
        )
    else:
        script_result = summarize(extraction)
    audio_bytes = synthesize(script_result)
    result = AudiobookResult(
        audio_bytes=audio_bytes,
        script=script_result.script,
        title=extraction.title,
    )
    return result, extraction


def run_from_file(path: Path, title: str | None = None, no_summary: bool = False) -> AudiobookResult:
    """Convenience wrapper that reads a file and runs the full pipeline."""
    result, _ = run_full_from_file(path, title=title, no_summary=no_summary)
    return result


def save_audio(
    result: AudiobookResult,
    output_dir: str | None = None,
    stem: str | None = None,
) -> Path:
    """Write MP3 bytes to disk. Returns the file path written.

    If `stem` is provided, use it verbatim as the filename stem; otherwise derive
    it from the title via ``safe_stem``. The `stem` override is used by batch
    processing to avoid filename collisions when multiple articles share a title.
    """
    settings = get_settings()
    out = Path(output_dir or settings.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    safe_title = stem if stem is not None else safe_stem(result.title)
    path = out / f"{safe_title}.mp3"
    path.write_bytes(result.audio_bytes)
    return path


def save_companion_pdf(
    result: AudiobookResult,
    output_dir: str | None = None,
    stem: str | None = None,
) -> Path | None:
    """Write companion PDF bytes (if any) next to the MP3. Returns path or None."""
    if result.companion_pdf_bytes is None:
        return None
    settings = get_settings()
    out = Path(output_dir or settings.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    safe_title = stem if stem is not None else safe_stem(result.title)
    path = out / f"{safe_title}.pdf"
    path.write_bytes(result.companion_pdf_bytes)
    return path


def save_manifest_for(
    result: AudiobookResult,
    extraction: ExtractionResult,
    audio_path: Path,
    pdf_path: Path | None,
    output_dir: str | None = None,
) -> Path:
    """Write the sidecar JSON manifest next to the MP3."""
    settings = get_settings()
    out = Path(output_dir or settings.output_dir)
    stem = audio_path.stem
    manifest = ArticleManifest(
        title=result.title,
        source_url=result.source_url,
        audio_filename=audio_path.name,
        pdf_filename=pdf_path.name if pdf_path else None,
        generated_at=now_iso(),
        word_count=extraction.word_count,
    )
    return write_manifest(manifest, out, stem)
