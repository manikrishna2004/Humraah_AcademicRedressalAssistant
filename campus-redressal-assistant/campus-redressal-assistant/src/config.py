"""
Central configuration for the Campus Redressal Assistant.

Every backend (LLM, embeddings, web search) is switchable between a
"mock" implementation, which runs fully offline with zero external calls,
and a production implementation (Ollama / sentence-transformers /
duckduckgo-search). This lets the LangGraph wiring itself be demoed,
inspected and unit-tested without a GPU or network access, then flipped
to real models with an env var change.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _bool(env_val: str | None, default: bool) -> bool:
    if env_val is None:
        return default
    return env_val.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # Backend switches
    llm_backend: str = field(default_factory=lambda: os.getenv("LLM_BACKEND", "mock"))
    embedding_backend: str = field(
        default_factory=lambda: os.getenv("EMBEDDING_BACKEND", "mock")
    )
    web_search_backend: str = field(
        default_factory=lambda: os.getenv("WEB_SEARCH_BACKEND", "mock")
    )

    # Ollama
    ollama_host: str = field(
        default_factory=lambda: os.getenv("OLLAMA_HOST", "http://localhost:11434")
    )
    ollama_model: str = field(
        default_factory=lambda: os.getenv("OLLAMA_MODEL", "llama3.1:8b")
    )

    # Embeddings
    embedding_model: str = field(
        default_factory=lambda: os.getenv("EMBEDDING_MODEL", "BAAI/bge-large-en-v1.5")
    )

    # Retrieval / gating
    confidence_threshold: float = field(
        default_factory=lambda: float(os.getenv("CONFIDENCE_THRESHOLD", "0.65"))
    )
    top_k: int = field(default_factory=lambda: int(os.getenv("TOP_K", "5")))

    # Storage
    sqlite_directory_db: str = field(
        default_factory=lambda: os.getenv("SQLITE_DIRECTORY_DB", "./data/directory.db")
    )
    chroma_persist_dir: str = field(
        default_factory=lambda: os.getenv("CHROMA_PERSIST_DIR", "./data/chroma")
    )
    checkpoint_db: str = field(
        default_factory=lambda: os.getenv("CHECKPOINT_DB", "./data/checkpoints.sqlite")
    )

    # Web search
    web_search_max_results: int = field(
        default_factory=lambda: int(os.getenv("WEB_SEARCH_MAX_RESULTS", "3"))
    )


settings = Settings()
