import asyncio
import io
import json
import re
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
from audio_articles.core.models import ArticleInput
from audio_articles.core.pipeline import run
from audio_articles.core.summarizer import summarize
from audio_articles.core.tts import synthesize
from audio_articles.core.qa import ask as qa_ask
from audio_articles.core.summarizer import summarize

from .schemas import ChatRequest, ChatResponse, ConvertRequest, FileInfo, ScriptResponse

router = APIRouter(prefix="/api/v1")
_executor = ThreadPoolExecutor(max_workers=4)

_VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]


async def _in_thread(fn, *args):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, fn, *args)


def _apply_voice(voice: str) -> None:
    from audio_articles.core.config import get_settings
    s = get_settings()
    object.__setattr__(s, "tts_voice", voice)


@router.get("/health", summary="Health check")
async def health():
    return {"status": "ok"}


@router.get("/voices", summary="List available TTS voices")
async def list_voices():
    return {"voices": _VOICES}


@router.get("/files", response_model=list[FileInfo], summary="List saved MP3 files")
async def list_files():
    """Return all MP3s in the output directory, newest first."""
    output_dir = Path(get_settings().output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for f in sorted(output_dir.glob("*.mp3"), key=lambda p: p.stat().st_ctime, reverse=True):
        stat = f.stat()
        files.append(FileInfo(
            name=f.stem,
            filename=f.name,
            size_bytes=stat.st_size,
            created_at=datetime.fromtimestamp(stat.st_ctime).isoformat(),
            url=f"/output/{quote(f.name)}",
        ))
    return files


@router.post(
    "/convert",
    response_class=StreamingResponse,
    summary="Convert article to MP3 (streams audio/mpeg)",
)
async def convert_article(req: ConvertRequest):
    """Accept a URL or raw text, run the full pipeline, and stream back an MP3."""
    if not req.url and not req.text:
        raise HTTPException(status_code=422, detail="Provide 'url' or 'text'.")

    if req.voice:
        _apply_voice(req.voice)

    article_input = ArticleInput(url=req.url, text=req.text, title=req.title, local=req.local)

    try:
        result = await _in_thread(run, article_input)
    except ExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except (SummarizationError, TTSError) as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except AudioArticlesError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    safe_title = result.title.replace(" ", "_")[:50]

    output_dir = Path(get_settings().output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    fs_title = re.sub(r'[^\w\s-]', '', result.title).strip()[:50] or "audio"
    (output_dir / f"{fs_title}.mp3").write_bytes(result.audio_bytes)

    return StreamingResponse(
        io.BytesIO(result.audio_bytes),
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_title}.mp3"',
            "X-Script-Word-Count": str(len(result.script.split())),
            "X-Article-Title": result.title,
        },
    )


@router.post(
    "/convert/stream",
    response_class=StreamingResponse,
    summary="Convert article to MP3 with step-by-step progress (SSE)",
)
async def convert_stream(req: ConvertRequest):
    """Streams Server-Sent Events: one per pipeline step, then a final 'done' event
    containing the URL of the saved MP3."""

    def _sse(data: dict) -> str:
        return f"data: {json.dumps(data)}\n\n"

    async def generate():
        try:
            if req.voice and not req.local:
                _apply_voice(req.voice)

            # Step 1 — fetch / extract
            if req.url:
                yield _sse({"status": "Fetching article\u2026", "step": 1, "total": 3})
                extraction = await _in_thread(fetch_and_extract, str(req.url))
                if req.title:
                    extraction = extraction.model_copy(update={"title": req.title})
            else:
                yield _sse({"status": "Extracting text\u2026", "step": 1, "total": 3})
                extraction = extract_from_text(req.text or "", title=req.title or "Article")

            # Step 2 — summarize
            summarizer_label = "Summarising with Ollama\u2026" if req.local else "Summarising with Claude\u2026"
            yield _sse({"status": summarizer_label, "step": 2, "total": 3})
            script_result = await _in_thread(lambda: summarize(extraction, local=req.local))

            # Step 3 — TTS
            tts_label = "Synthesising with edge-tts\u2026" if req.local else "Synthesising audio\u2026"
            yield _sse({"status": tts_label, "step": 3, "total": 3})
            audio_bytes = await _in_thread(lambda: synthesize(script_result, local=req.local))

            # Save to disk
            output_dir = Path(get_settings().output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            fs_title = re.sub(r"[^\w\s-]", "", extraction.title).strip()[:50] or "audio"
            output_path = output_dir / f"{fs_title}.mp3"
            output_path.write_bytes(audio_bytes)

            yield _sse({
                "status": "done",
                "url": f"/output/{quote(output_path.name)}",
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
    """Extract and summarize an article. Returns the script text without generating audio."""
    if not req.url and not req.text:
        raise HTTPException(status_code=422, detail="Provide 'url' or 'text'.")

    try:
        if req.url:
            extraction = await _in_thread(fetch_and_extract, str(req.url))
        else:
            extraction = extract_from_text(req.text or "", title=req.title or "Article")

        script_result = await _in_thread(summarize, extraction)
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
