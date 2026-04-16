import asyncio
import io
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from audio_articles.core.exceptions import (
    AudioArticlesError,
    ExtractionError,
    SummarizationError,
    TTSError,
)
from audio_articles.core.fetcher import extract_from_text, fetch_and_extract
from audio_articles.core.models import ArticleInput, ScriptResult
from audio_articles.core.pipeline import run
from audio_articles.core.qa import ask as qa_ask
from audio_articles.core.summarizer import summarize

from .schemas import ChatRequest, ChatResponse, ConvertRequest, ScriptResponse

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


def _apply_words(words: int) -> None:
    from audio_articles.core.config import get_settings
    s = get_settings()
    object.__setattr__(s, "script_word_target", words)


@router.get("/health", summary="Health check")
async def health():
    return {"status": "ok"}


@router.get("/voices", summary="List available TTS voices")
async def list_voices():
    return {"voices": _VOICES}


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
    if req.words:
        _apply_words(req.words)

    article_input = ArticleInput(url=req.url, text=req.text, title=req.title, no_summary=req.no_summary)

    try:
        result = await _in_thread(run, article_input)
    except ExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except (SummarizationError, TTSError) as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except AudioArticlesError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    safe_title = result.title.replace(" ", "_")[:50]
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
    "/script",
    response_model=ScriptResponse,
    summary="Generate script only (no TTS — use to preview before converting)",
)
async def get_script(req: ConvertRequest):
    """Extract and summarize an article. Returns the script text without generating audio."""
    if not req.url and not req.text:
        raise HTTPException(status_code=422, detail="Provide 'url' or 'text'.")

    if req.words:
        _apply_words(req.words)

    try:
        if req.url:
            extraction = await _in_thread(fetch_and_extract, str(req.url))
        else:
            extraction = extract_from_text(req.text or "", title=req.title or "Article")

        if req.no_summary:
            script_result = ScriptResult(
                script=extraction.body,
                word_count=extraction.word_count,
                chunks_used=1,
            )
        else:
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
