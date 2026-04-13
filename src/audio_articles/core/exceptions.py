class AudioArticlesError(Exception):
    """Base exception for all audio-articles errors."""


class ExtractionError(AudioArticlesError):
    """Raised when article text cannot be extracted from a URL or input."""


class SummarizationError(AudioArticlesError):
    """Raised when the Claude API fails or returns unusable output."""


class TTSError(AudioArticlesError):
    """Raised when the OpenAI TTS API fails."""
