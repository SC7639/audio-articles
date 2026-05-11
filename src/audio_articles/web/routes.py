import asyncio
import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from audio_articles.core.config import get_settings
from audio_articles.core.exceptions import (
    AudioArticlesError,
    ExtractionError,
    SummarizationError,
    TTSError,
)
from audio_articles.core.fetcher import extract_from_text, fetch_and_extract
from audio_articles.core.manifest import read_manifest
from audio_articles.core.models import ArticleInput, AudiobookResult, ScriptResult
from audio_articles.core.pipeline import (
    fetch_and_maybe_render_pdf,
    run_full,
    save_audio,
    save_companion_pdf,
    save_manifest_for,
)
from audio_articles.core.qa import ask as qa_ask
from audio_articles.core.summarizer import summarize
from audio_articles.core.tts import synthesize

from .schemas import ChatRequest, ChatResponse, ConvertRequest, FileInfo, ScriptResponse

router = APIRouter(prefix="/api/v1")
_executor = ThreadPoolExecutor(max_workers=4)

_VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]


async def _in_thread(fn, *args):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, fn, *args)


def _apply_voice(voice: str) -> None:
    s = get_settings()
    object.__setattr__(s, "tts_voice", voice)


def _apply_words(words: int) -> None:
    s = get_settings()
    object.__setattr__(s, "script_word_target", words)


def _output_url(filename: str) -> str:
    return f"/output/{quote(filename)}"


@router.get("/health", summary="Health check")
async def health():
    return {"status": "ok"}


@router.get("/voices", summary="List available TTS voices")
async def list_voices():
    return {"voices": _VOICES}


@router.get("/files", response_model=list[FileInfo], summary="List saved audio files and their companion PDFs")
async def list_files():
    """Return all MP3s in the output directory, newest first.

    For each MP3 we look for a matching ``{stem}.pdf`` and ``{stem}.json`` (sidecar
    manifest) and surface them so the library page can show a download link and
    the source URL alongside the audio player.
    """
    output_dir = Path(get_settings().output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for f in sorted(output_dir.glob("*.mp3"), key=lambda p: p.stat().st_ctime, reverse=True):
        stat = f.stat()
        pdf_path = output_dir / f"{f.stem}.pdf"
        manifest = read_manifest(output_dir, f.stem)
        pdf_url = _output_url(pdf_path.name) if pdf_path.exists() else None
        pdf_size = pdf_path.stat().st_size if pdf_path.exists() else None
        files.append(FileInfo(
            name=manifest.title if manifest else f.stem,
            filename=f.name,
            size_bytes=stat.st_size,
            created_at=datetime.fromtimestamp(stat.st_ctime).isoformat(),
            url=_output_url(f.name),
            pdf_url=pdf_url,
            pdf_size_bytes=pdf_size,
            source_url=manifest.source_url if manifest else None,
        ))
    return files


def _article_input_from_req(req: ConvertRequest) -> ArticleInput:
    return ArticleInput(
        url=req.url,
        text=req.text,
        title=req.title,
        local=req.local,
        no_summary=req.no_summary,
        companion_pdf=req.companion_pdf,
    )


def _save_all(result: AudiobookResult, extraction) -> tuple[Path, Path | None]:
    """Persist MP3, optional PDF, and manifest. Returns (audio_path, pdf_path)."""
    audio_path = save_audio(result)
    pdf_path = save_companion_pdf(result)
    save_manifest_for(result, extraction, audio_path, pdf_path)
    return audio_path, pdf_path


@router.post(
    "/convert",
    response_class=StreamingResponse,
    summary="Convert article to MP3 (streams audio/mpeg). Companion PDF is saved alongside when generated.",
)
async def convert_article(req: ConvertRequest):
    """Run the full pipeline and stream back the MP3.

    A companion PDF is rendered and saved next to the MP3 whenever the source
    article contains code blocks or images. The PDF download URL is exposed via
    the ``X-Companion-PDF-URL`` response header.
    """
    if not req.url and not req.text:
        raise HTTPException(status_code=422, detail="Provide 'url' or 'text'.")

    if req.voice:
        _apply_voice(req.voice)
    if req.words:
        _apply_words(req.words)

    article_input = _article_input_from_req(req)

    try:
        result, extraction = await _in_thread(run_full, article_input)
    except ExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except (SummarizationError, TTSError) as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except AudioArticlesError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    audio_path, pdf_path = _save_all(result, extraction)

    headers = {
        "Content-Disposition": f'attachment; filename="{audio_path.name}"',
        "X-Script-Word-Count": str(len(result.script.split())),
        "X-Article-Title": result.title,
    }
    if pdf_path:
        headers["X-Companion-PDF-URL"] = _output_url(pdf_path.name)

    return StreamingResponse(
        io.BytesIO(result.audio_bytes),
        media_type="audio/mpeg",
        headers=headers,
    )


@router.post(
    "/convert/stream",
    response_class=StreamingResponse,
    summary="Convert article to MP3 with step-by-step progress (SSE)",
)
async def convert_stream(req: ConvertRequest):
    """Stream Server-Sent Events: one per pipeline step, then a final ``done`` event
    with the URLs of the saved MP3 and (optionally) the companion PDF."""

    def _sse(data: dict) -> str:
        return f"data: {json.dumps(data)}\n\n"

    article_input = _article_input_from_req(req)

    async def generate():
        try:
            if req.voice and not req.local:
                _apply_voice(req.voice)

            yield _sse({
                "status": "Fetching article…" if req.url else "Extracting text…",
                "step": 1,
                "total": 3,
            })
            extraction, pdf_bytes = await _in_thread(fetch_and_maybe_render_pdf, article_input)

            if req.no_summary:
                script_result = ScriptResult(
                    script=extraction.body,
                    word_count=extraction.word_count,
                    chunks_used=1,
                )
            else:
                summarizer_label = "Summarising with Ollama…" if req.local else "Summarising with Claude…"
                yield _sse({"status": summarizer_label, "step": 2, "total": 3})
                script_result = await _in_thread(lambda: summarize(extraction, local=req.local))

            tts_label = "Synthesising with edge-tts…" if req.local else "Synthesising audio…"
            yield _sse({"status": tts_label, "step": 3, "total": 3})
            audio_bytes = await _in_thread(lambda: synthesize(script_result, local=req.local))

            result = AudiobookResult(
                audio_bytes=audio_bytes,
                script=script_result.script,
                title=extraction.title,
                source_url=str(req.url) if req.url else None,
                companion_pdf_bytes=pdf_bytes,
            )
            audio_path, pdf_path = _save_all(result, extraction)

            yield _sse({
                "status": "done",
                "url": _output_url(audio_path.name),
                "pdf_url": _output_url(pdf_path.name) if pdf_path else None,
                "title": extraction.title,
                "words": script_result.word_count,
            })

        except ExtractionError as exc:
            yield _sse({"status": "error", "message": str(exc)})
        except (SummarizationError, TTSError) as exc:
            yield _sse({"status": "error", "message": str(exc)})
        except AudioArticlesError as exc:
            yield _sse({"status": "error", "message": str(exc)})

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post(
    "/script",
    response_model=ScriptResponse,
    summary="Generate script only (no TTS — use to preview before converting)",
)
async def get_script(req: ConvertRequest):
    """Extract and summarize an article. Returns the script text without generating audio.

    When ``companion_pdf`` is true (and a URL is provided) the script preview will
    include ``(See code block N…)`` references that match a paired PDF — the PDF
    bytes are dropped here, but the markers reflect the script the eventual audio
    would narrate.
    """
    if not req.url and not req.text:
        raise HTTPException(status_code=422, detail="Provide 'url' or 'text'.")

    if req.words:
        _apply_words(req.words)

    article_input = _article_input_from_req(req)

    try:
        extraction, _pdf_bytes = await _in_thread(fetch_and_maybe_render_pdf, article_input)

        if req.no_summary:
            script_result = ScriptResult(
                script=extraction.body,
                word_count=extraction.word_count,
                chunks_used=1,
            )
        else:
            script_result = await _in_thread(lambda: summarize(extraction, local=req.local))
    except ExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except SummarizationError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return ScriptResponse(
        title=extraction.title,
        script=script_result.script,
        word_count=script_result.word_count,
        source_url=str(req.url) if req.url else None,
        chunks_used=script_result.chunks_used,
        companion_pdf_url=None,  # /script never persists; library page is the canonical PDF source
    )


@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="Ask a question about an article",
)
async def chat_article(req: ChatRequest) -> ChatResponse:
    """Extract the article then answer a question using Claude.

    The article body is prompt-cached on the Claude side, so repeated questions
    about the same article are significantly cheaper after the first call.
    """
    if not req.url and not req.text:
        raise HTTPException(status_code=422, detail="Provide 'url' or 'text'.")

    try:
        if req.url:
            extraction = await _in_thread(fetch_and_extract, str(req.url))
        else:
            extraction = extract_from_text(req.text or "", title=req.title or "Article")
    except ExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        answer = await _in_thread(qa_ask, req.question, extraction, req.history or [])
    except SummarizationError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except AudioArticlesError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return ChatResponse(answer=answer)


@router.post(
    "/convert/upload",
    response_class=StreamingResponse,
    summary="Upload a text file and convert to audiobook",
)
async def convert_upload(
    file: UploadFile = File(..., description="Plain text file"),
    title: str = Form(default="Article"),
    voice: str = Form(default=None),
):
    content = await file.read()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=422, detail="File must be UTF-8 encoded text.")

    req = ConvertRequest(text=text, title=title, voice=voice)
    return await convert_article(req)
