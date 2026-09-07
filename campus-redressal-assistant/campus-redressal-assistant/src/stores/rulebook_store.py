"""
Official Rulebooks & Curricula Collection (ChromaDB Collection B).

Stores chunked PDFs of academic ordinances / UG rulebooks / branch curricula.
Queried with Hybrid Search: BM25 keyword matching fused with dense vector
similarity via Reciprocal Rank Fusion (RRF), per the architecture spec.
"""
from __future__ import annotations

import json
import pickle
import re
from pathlib import Path
from typing import Any

from rank_bm25 import BM25Okapi

from src.config import settings
from src.embeddings import get_embedding_function
from src.stores.chroma_client import get_client

_COLLECTION_NAME = "official_rulebook"
_BM25_INDEX_PATH = Path(settings.chroma_persist_dir) / "bm25_rulebook.pkl"
_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Minimal English stopword list -- BM25's IDF term already down-weights
# very common words, but with a corpus this small (a handful of rulebook
# chunks) that alone isn't enough: a handful of shared stopwords between an
# unrelated query and a chunk can still move the score more than it should.
_STOPWORDS = frozenset(
    """
    a an the is are was were be been being to of in on for and or but if
    what when where who how why this that these those it its i you he
    she they we do does did have has had will would should can could
    with as at by from not no so than then there here also
    """.split()
)


def _tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]


def _collection():
    return get_client().get_or_create_collection(
        name=_COLLECTION_NAME,
        embedding_function=get_embedding_function(),
        metadata={"hnsw:space": "cosine"},
    )


def load_json(path: str | Path) -> None:
    """
    Ingest data/rulebook_chunks.json -- a list of objects shaped like:
        {"subcategory": "...", "department": "...", "text": "..."}
    Builds both the Chroma dense index and a parallel BM25 index (pickled
    alongside the Chroma persistence dir so both stay in sync).
    """
    entries: list[dict[str, Any]] = json.loads(Path(path).read_text(encoding="utf-8"))
    col = _collection()

    ids = [f"rule-{i}" for i in range(len(entries))]
    documents = [e["text"] for e in entries]
    metadatas = [
        {
            "subcategory": e.get("subcategory", ""),
            "department": e.get("department", "General"),
        }
        for e in entries
    ]

    existing = col.get(ids=ids)
    if existing["ids"]:
        col.delete(ids=existing["ids"])
    col.add(ids=ids, documents=documents, metadatas=metadatas)

    tokenized = [_tokenize(doc) for doc in documents]
    bm25 = BM25Okapi(tokenized)
    _BM25_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_BM25_INDEX_PATH, "wb") as f:
        pickle.dump({"bm25": bm25, "ids": ids, "documents": documents, "metadatas": metadatas}, f)


def _load_bm25():
    if not _BM25_INDEX_PATH.exists():
        return None
    with open(_BM25_INDEX_PATH, "rb") as f:
        return pickle.load(f)


def _reciprocal_rank_fusion(
    ranked_lists: list[list[str]], k: int = 60
) -> dict[str, float]:
    """Standard RRF: score(d) = sum over lists of 1 / (k + rank_in_list)."""
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, doc_id in enumerate(ranked):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return scores


def query_rulebook(
    query: str,
    department: str | None = None,
    top_k: int = 5,
) -> list[dict]:
    """
    RRF fuses the dense and sparse *rankings* to decide which chunks to
    surface and in what order -- that is what RRF is for. But RRF's own
    fused number is a rank-based score (1/(k+rank)), which compresses
    quickly across a handful of documents and is a poor absolute confidence
    signal (rank 5 of 5 still scores close to rank 1 after normalization).
    So the Confidence & Similarity Gate is instead given, per surfaced
    chunk, the strongest *magnitude* signal available for it -- dense
    cosine similarity or normalized BM25 -- while RRF still governs which
    chunks appear and their order.
    """
    # -- dense branch --
    col = _collection()
    where = {"department": {"$in": [department, "General"]}} if department else None
    dense_result = col.query(query_texts=[query], n_results=top_k, where=where)
    dense_ids = dense_result["ids"][0] if dense_result["ids"] else []

    doc_lookup: dict[str, dict] = {}
    dense_similarity: dict[str, float] = {}
    if dense_ids:
        for doc_id, doc, meta, distance in zip(
            dense_ids,
            dense_result["documents"][0],
            dense_result["metadatas"][0],
            dense_result["distances"][0],
        ):
            doc_lookup[doc_id] = {"text": doc, "metadata": meta}
            dense_similarity[doc_id] = max(0.0, 1.0 - float(distance))  # cosine space

    # -- sparse (BM25) branch --
    bm25_data = _load_bm25()
    sparse_ids: list[str] = []
    bm25_normalized: dict[str, float] = {}
    if bm25_data is not None:
        bm25: BM25Okapi = bm25_data["bm25"]
        all_ids = bm25_data["ids"]
        raw_scores = [float(s) for s in bm25.get_scores(_tokenize(query))]
        max_raw = max(raw_scores) if raw_scores else 0.0

        ranked = sorted(zip(all_ids, raw_scores), key=lambda x: x[1], reverse=True)
        for doc_id, doc, meta in zip(all_ids, bm25_data["documents"], bm25_data["metadatas"]):
            doc_lookup.setdefault(doc_id, {"text": doc, "metadata": meta})

        for doc_id, raw in ranked:
            meta = doc_lookup.get(doc_id, {}).get("metadata", {})
            if department and meta.get("department") not in (department, "General"):
                continue  # keep department filtering consistent with the dense branch
            sparse_ids.append(doc_id)
            bm25_normalized[doc_id] = float(raw / max_raw) if max_raw > 0 else 0.0
        sparse_ids = sparse_ids[:top_k]

    # -- fuse via Reciprocal Rank Fusion to pick + order the final chunk set --
    fused_scores = _reciprocal_rank_fusion([dense_ids, sparse_ids])
    if not fused_scores:
        return []
    ranked_ids = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]

    hits = []
    for doc_id, _rrf_score in ranked_ids:
        info = doc_lookup.get(doc_id, {"text": "", "metadata": {}})
        magnitude = max(dense_similarity.get(doc_id, 0.0), bm25_normalized.get(doc_id, 0.0))
        hits.append(
            {
                "text": info["text"],
                "tag": info["metadata"].get("subcategory", ""),
                "score": round(magnitude, 4),
                "metadata": info["metadata"],
            }
        )
    return hits
