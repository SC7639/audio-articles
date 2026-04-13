from pydantic import BaseModel, HttpUrl


class ConvertRequest(BaseModel):
    url: HttpUrl | None = None
    text: str | None = None
    title: str | None = None
    voice: str | None = None


class ScriptResponse(BaseModel):
    title: str
    script: str
    word_count: int
    source_url: str | None = None
    chunks_used: int
