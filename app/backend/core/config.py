from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="app/backend/.env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM provider selection: "ollama", "openrouter", or "vllm"
    llm_provider: str = Field("ollama", alias="LLM_PROVIDER")

    # Ollama (local)
    ollama_base_url: str = Field("http://localhost:11434/v1", alias="OLLAMA_BASE_URL")
    ollama_model: str = Field("llama3.2:latest", alias="OLLAMA_MODEL")

    # OpenRouter (cloud fallback — only required when LLM_PROVIDER=openrouter)
    openrouter_api_key: str = Field("", alias="OPENROUTER_API_KEY")
    openrouter_model: str = Field("google/gemma-4-31b-it:free", alias="OPENROUTER_MODEL")

    # vLLM (cluster-internal inference server — used when LLM_PROVIDER=vllm)
    # Primary Harvey endpoint; secondary is optional for load-balancing the 3 parallel Harvey calls.
    vllm_base_url: str = Field("", alias="VLLM_BASE_URL")
    vllm_base_url_2: str = Field("", alias="VLLM_BASE_URL_2")
    vllm_base_model: str = Field("google/gemma-4-26B-A4B-it", alias="VLLM_BASE_MODEL")

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
        default=["http://localhost:5173", "http://127.0.0.1:5173"],
        alias="ALLOWED_FRONTEND_ORIGINS",
    )
    cors_origins: list[str] = Field(
        default=["http://localhost:5173", "http://127.0.0.1:5173"],
        alias="CORS_ORIGINS",
    )

    # Parser / OCR
    enable_ocr_fallback: bool = Field(True, alias="ENABLE_OCR_FALLBACK")
    parser_version: str = Field("docling-1", alias="PARSER_VERSION")
    parser_primary: str = Field("docling", alias="PARSER_PRIMARY")
    ocr_enabled: bool = Field(True, alias="OCR_ENABLED")
    pdfplumber_fallback_enabled: bool = Field(True, alias="PDFPLUMBER_FALLBACK_ENABLED")

    # RAG / embeddings
    rag_max_file_mb: int = Field(50, alias="RAG_MAX_FILE_MB")
    rag_max_pages: int = Field(500, alias="RAG_MAX_PAGES")
    rag_chunk_size: int = Field(800, alias="RAG_CHUNK_SIZE")
    rag_chunk_overlap: int = Field(100, alias="RAG_CHUNK_OVERLAP")
    rag_top_k: int = Field(20, alias="RAG_TOP_K")
    rag_rerank_top_k: int = Field(5, alias="RAG_RERANK_TOP_K")
    rag_storage_path: str = Field("./storage/rag", alias="RAG_STORAGE_PATH")
    embedding_provider: str = Field("local", alias="EMBEDDING_PROVIDER")
    embedding_model_name: str = Field("sentence-transformers/all-MiniLM-L6-v2", alias="EMBEDDING_MODEL_NAME")
    embedding_base_url: str = Field("http://localhost:11434/api", alias="EMBEDDING_BASE_URL")
    embedding_dimensions: int = Field(1536, alias="EMBEDDING_DIMENSIONS")
    pgvector_enabled: bool = Field(True, alias="PGVECTOR_ENABLED")

    # Registry / observability
    model_registry_path: str = Field("configs/models.yaml", alias="MODEL_REGISTRY_PATH")
    metrics_enabled: bool = Field(True, alias="METRICS_ENABLED")
    reviewer_temperature: float = Field(0.2, alias="REVIEWER_TEMPERATURE")
    validator_temperature: float = Field(0.1, alias="VALIDATOR_TEMPERATURE")

    # Kira fine-tuned model (set after training is deployed to cloud)
    # If kira_model_url is set, Kira uses this endpoint instead of the default provider.
    # Example: KIRA_MODEL_URL=http://kira-service:8080/v1
    kira_model_url: str = Field("", alias="KIRA_MODEL_URL")
    kira_model_name: str = Field("kira-gemma4-26b", alias="KIRA_MODEL_NAME")


    @model_validator(mode="after")
    def _validate_llm_urls(self) -> "Settings":
        if self.llm_provider != "vllm":
            return self
        for field_name, url in (
            ("VLLM_BASE_URL", self.vllm_base_url),
            ("KIRA_MODEL_URL", self.kira_model_url),
        ):
            if not url:
                continue
            if "#" in url:
                raise ValueError(
                    f"{field_name}={url!r} contains a URL fragment (#). "
                    "Use the RunPod API base ending in /v1, not the browser chat link."
                )
            if "proxy.runpod.net" in url and not url.rstrip("/").endswith("/v1"):
                raise ValueError(
                    f"{field_name}={url!r} does not end in /v1. "
                    "Use the RunPod API base (e.g. https://<pod>-8000.proxy.runpod.net/v1)."
                )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


SettingsDep = Annotated[Settings, Depends(get_settings)]
