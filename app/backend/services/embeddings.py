from __future__ import annotations

import math
from abc import ABC, abstractmethod

import httpx

from app.backend.core.config import Settings, get_settings


def _l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        return vector
    return [v / norm for v in vector]


class EmbeddingProvider(ABC):
    dimensions: int
    model_name: str

    @abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class LocalEmbeddingProvider(EmbeddingProvider):
    def __init__(self, model_name: str, dimensions: int) -> None:
        self.model_name = model_name
        self.dimensions = dimensions
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # type: ignore

            self._model = SentenceTransformer(self.model_name)
        return self._model

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._load().encode(texts, batch_size=32, normalize_embeddings=True)
        return [list(map(float, vector)) for vector in vectors]


class OpenAICompatibleEmbeddingProvider(EmbeddingProvider):
    def __init__(self, base_url: str, model_name: str, dimensions: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.dimensions = dimensions

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        with httpx.Client(timeout=60.0) as client:
            for start in range(0, len(texts), 32):
                batch = texts[start : start + 32]
                response = client.post(
                    f"{self.base_url}/embeddings",
                    json={"model": self.model_name, "input": batch},
                )
                response.raise_for_status()
                payload = response.json()
                vectors.extend(_l2_normalize(item["embedding"]) for item in payload.get("data", []))
        return vectors


class DeterministicHashEmbeddingProvider(EmbeddingProvider):
    """Dependency-free fallback for tests and offline scaffolding."""

    def __init__(self, dimensions: int = 1536, model_name: str = "hash-fallback") -> None:
        self.dimensions = dimensions
        self.model_name = model_name

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        import hashlib

        vectors: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            raw = [((digest[i % len(digest)] / 255.0) * 2) - 1 for i in range(self.dimensions)]
            vectors.append(_l2_normalize(raw))
        return vectors


def get_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    settings = settings or get_settings()
    provider = settings.embedding_provider.lower()
    if provider in {"ollama", "openai_compatible", "openai-compatible"}:
        return OpenAICompatibleEmbeddingProvider(
            settings.embedding_base_url,
            settings.embedding_model_name,
            settings.embedding_dimensions,
        )
    if provider in {"hash", "deterministic", "test"}:
        return DeterministicHashEmbeddingProvider(settings.embedding_dimensions)
    return LocalEmbeddingProvider(settings.embedding_model_name, settings.embedding_dimensions)
