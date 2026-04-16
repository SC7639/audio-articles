from pydantic import BaseModel, HttpUrl

from audio_articles.core.models import QATurn  # noqa: F401 — re-exported for routes


class ConvertRequest(BaseModel):
    url: HttpUrl | None = None
    text: str | None = None
    title: str | None = None
    voice: str | None = None
    local: bool = False


class ScriptResponse(BaseModel):
    title: str
    script: str
    word_count: int
    source_url: str | None = None
    chunks_used: int


class ChatRequest(BaseModel):
    url: HttpUrl | None = None
    text: str | None = None
    title: str | None = None
    question: str
    history: list[QATurn] = []


class ChatResponse(BaseModel):
    answer: str


class FileInfo(BaseModel):
    name: str
    filename: str
    size_bytes: int
    created_at: str
    url: str
