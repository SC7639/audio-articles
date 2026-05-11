from pydantic import BaseModel, HttpUrl, model_validator


class ArticleInput(BaseModel):
    """Input to the pipeline — exactly one of url or text must be provided."""

    url: HttpUrl | None = None
    text: str | None = None
    title: str | None = None
    cookies: dict[str, str] | None = None
    local: bool = False
    no_summary: bool = False
    companion_pdf: bool = True

    @model_validator(mode="after")
    def _require_source(self) -> "ArticleInput":
        if self.url is None and self.text is None:
            raise ValueError("Provide either 'url' or 'text'.")
        return self


class ExtractionResult(BaseModel):
    title: str
    body: str
    source_url: str | None = None
    word_count: int


class CodeBlock(BaseModel):
    content: str
    language: str | None = None


class ImageAsset(BaseModel):
    local_filename: str
    alt_text: str | None = None
    caption: str | None = None
    is_svg: bool = False


class ArticleAssets(BaseModel):
    code_blocks: list[CodeBlock] = []
    images: list[ImageAsset] = []

    @property
    def is_empty(self) -> bool:
        return not (self.code_blocks or self.images)


class ScriptResult(BaseModel):
    script: str
    word_count: int
    chunks_used: int = 1


class AudiobookResult(BaseModel):
    audio_bytes: bytes
    script: str
    title: str
    source_url: str | None = None
    format: str = "mp3"
    companion_pdf_bytes: bytes | None = None

    model_config = {"arbitrary_types_allowed": True}


class QATurn(BaseModel):
    """A single question-answer exchange for multi-turn article Q&A."""

    question: str
    answer: str
