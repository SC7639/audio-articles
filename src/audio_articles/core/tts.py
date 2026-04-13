import re

from openai import OpenAI

from .config import get_settings
from .exceptions import TTSError
from .models import ScriptResult

# OpenAI TTS supports roughly 4096 tokens (~3000 words) per request.
_WORD_LIMIT = 2800


def synthesize(script_result: ScriptResult) -> bytes:
    """Convert a ScriptResult to MP3 audio bytes using OpenAI tts-1-hd."""
    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)
    script = script_result.script

    words = script.split()
    if len(words) <= _WORD_LIMIT:
        return _single_tts(client, script, settings)

    # Long script: split at sentence boundaries and concatenate raw MP3 frames
    segments = _split_at_sentences(script, _WORD_LIMIT)
    parts = [_single_tts(client, seg, settings) for seg in segments]
    return b"".join(parts)


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
