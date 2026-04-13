from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    anthropic_api_key: str = ""
    openai_api_key: str = ""

    claude_model: str = "claude-sonnet-4-6"
    tts_voice: str = "onyx"
    summarizer_max_tokens: int = 2048
    script_word_target: int = 400

    # Long-article chunking thresholds (characters)
    chunk_threshold_chars: int = 12_000
    chunk_size_chars: int = 8_000
    chunk_overlap_chars: int = 500

    host: str = "0.0.0.0"
    port: int = 8000
    output_dir: str = "./output"


@lru_cache
def get_settings() -> Settings:
    return Settings()
