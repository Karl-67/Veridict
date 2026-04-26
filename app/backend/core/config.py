from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="app/backend/.env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM provider selection: "ollama" or "openrouter"
    llm_provider: str = Field("ollama", alias="LLM_PROVIDER")

    # Ollama (local)
    ollama_base_url: str = Field("http://localhost:11434/v1", alias="OLLAMA_BASE_URL")
    ollama_model: str = Field("llama3.2:latest", alias="OLLAMA_MODEL")

    # OpenRouter (cloud fallback — only required when LLM_PROVIDER=openrouter)
    openrouter_api_key: str = Field("", alias="OPENROUTER_API_KEY")
    openrouter_model: str = Field("google/gemma-4-31b-it:free", alias="OPENROUTER_MODEL")

    # Gemini / LLM provider (kept for backwards compat — no longer used)
    gemini_api_key: str = Field("", alias="GEMINI_API_KEY")
    gemini_model_name: str = Field("gemini-2.0-flash-lite", alias="GEMINI_MODEL_NAME")

    # Postgres
    postgres_dsn: str = Field(..., alias="POSTGRES_DSN")

    # Worker
    worker_lease_duration_seconds: int = Field(60, alias="WORKER_LEASE_DURATION_SECONDS")
    max_stage_retries: int = Field(3, alias="MAX_STAGE_RETRIES")

    # Storage
    document_storage_path: str = Field("./storage/documents", alias="DOCUMENT_STORAGE_PATH")

    # CORS
    allowed_frontend_origins: list[str] = Field(
        default=["http://localhost:5173"],
        alias="ALLOWED_FRONTEND_ORIGINS",
    )

    # Parser / OCR
    enable_ocr_fallback: bool = Field(True, alias="ENABLE_OCR_FALLBACK")
    parser_version: str = Field("docling-1", alias="PARSER_VERSION")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


SettingsDep = Annotated[Settings, Depends(get_settings)]
