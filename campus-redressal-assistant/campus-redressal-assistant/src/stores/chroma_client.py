"""
Both ChromaDB collections (Senior Experience Store, Official Rulebook Store)
are queried concurrently inside Node 2's asyncio.gather(). ChromaDB's
PersistentClient is not safe to instantiate twice, concurrently, against
the same on-disk path from different threads -- so both stores share a
single lazily-created, thread-locked client instance instead of opening
their own.
"""
from __future__ import annotations

import threading

import chromadb

from src.config import settings

_lock = threading.Lock()
_client: chromadb.ClientAPI | None = None


def get_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                _client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
    return _client
