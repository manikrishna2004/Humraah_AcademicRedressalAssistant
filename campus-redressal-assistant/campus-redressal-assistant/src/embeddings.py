"""
Embedding function for the two ChromaDB collections (Senior Experience Store,
Official Rulebook Store).

Two implementations, selected by EMBEDDING_BACKEND:

- "mock": a dependency-light, fully offline feature-hashing vectorizer.
  Not semantically meaningful -- it exists so the retrieval + confidence-gate
  wiring can be exercised and unit-tested without downloading a model.
- "sentence-transformers": the real BAAI/bge-large-en-v1.5 model specified
  in the architecture, downloaded from HuggingFace on first use.
"""
from __future__ import annotations

import hashlib
import math
import re
from functools import lru_cache
from typing import Any

from chromadb.api.types import EmbeddingFunction

from src.config import settings

_TOKEN_RE = re.compile(r"[a-z0-9]+")


class HashingEmbeddingFunction(EmbeddingFunction):
    """Offline bag-of-words feature-hashing embedder (dev/demo mode)."""

    def __init__(self, dim: int = 384):
        self.dim = dim

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = _TOKEN_RE.findall(text.lower())
        if not tokens:
            return vec
        for tok in tokens:
            h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
            idx = h % self.dim
            sign = 1.0 if (h // self.dim) % 2 == 0 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def __call__(self, input: list[str]) -> list[list[float]]:  # noqa: A002
        return [self._embed_one(t) for t in input]

    @staticmethod
    def name() -> str:
        return "hashing-dev-embedder"

    def get_config(self) -> dict[str, Any]:
        return {"dim": self.dim}

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> "HashingEmbeddingFunction":
        return HashingEmbeddingFunction(dim=config.get("dim", 384))


class SentenceTransformerEmbeddingFunction(EmbeddingFunction):
    """Production embedder: BAAI/bge-large-en-v1.5 (or any ST-compatible model)."""

    def __init__(self, model_name: str = "BAAI/bge-large-en-v1.5"):
        from sentence_transformers import SentenceTransformer  # local import: heavy dep

        self.model_name = model_name
        self.model = SentenceTransformer(model_name)

    def __call__(self, input: list[str]) -> list[list[float]]:  # noqa: A002
        embeddings = self.model.encode(
            list(input), normalize_embeddings=True, show_progress_bar=False
        )
        return embeddings.tolist()

    @staticmethod
    def name() -> str:
        return "sentence-transformers"

    def get_config(self) -> dict[str, Any]:
        return {"model_name": self.model_name}

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> "SentenceTransformerEmbeddingFunction":
        return SentenceTransformerEmbeddingFunction(
            model_name=config.get("model_name", "BAAI/bge-large-en-v1.5")
        )


@lru_cache(maxsize=1)
def get_embedding_function():
    if settings.embedding_backend == "sentence-transformers":
        return SentenceTransformerEmbeddingFunction(settings.embedding_model)
    return HashingEmbeddingFunction()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)
