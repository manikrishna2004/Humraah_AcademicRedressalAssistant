"""
Senior Experience Vector Collection (ChromaDB Collection A).

Stores normalized crowdsourced entries (Category, Subcategory, Department,
Senior Navigation Summary) sourced from a Google Form, indexed with dense
embeddings and queried by cosine similarity filtered by metadata
(department / program), per the architecture spec.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.embeddings import get_embedding_function
from src.stores.chroma_client import get_client

_COLLECTION_NAME = "senior_experience"


def _collection(campus: bool = False):
    return get_client().get_or_create_collection(
        name=f"{_COLLECTION_NAME}_campus_examples" if campus else _COLLECTION_NAME,
        embedding_function=get_embedding_function(),
        metadata={"hnsw:space": "cosine"},
    )


def load_json(path: str | Path, *, campus: bool = False) -> None:
    """
    Ingest data/senior_experiences.json -- a list of objects shaped like:
        {"category": "...", "subcategory": "...", "department": "...",
         "degree_program": "...", "summary": "..."}
    """
    entries: list[dict[str, Any]] = json.loads(Path(path).read_text(encoding="utf-8"))
    col = _collection(campus)

    ids = [f"senior-{i}" for i in range(len(entries))]
    documents = [e["summary"] for e in entries]
    metadatas = [
        {
            "category": e.get("category", ""),
            "title": e.get("title", ""),
            "subcategory": e.get("subcategory", ""),
            "department": e.get("department", ""),
            "degree_program": e.get("degree_program", ""),
            "policy_difference": e.get("policy_difference", ""),
        }
        for e in entries
    ]

    # idempotent re-ingest
    existing = col.get(include=[])
    if existing["ids"]:
        col.delete(ids=existing["ids"])
    col.add(ids=ids, documents=documents, metadatas=metadatas)


def query_senior_experience(
    query: str,
    department: str | None = None,
    top_k: int = 5,
    *,
    tags: tuple[str, ...] = (),
    program: str | None = None,
    campus: bool = False,
) -> list[dict]:
    col = _collection(campus)
    filters = []
    if department:
        filters.append({"department": {"$in": [department, "General"]}} if campus and department != "General" else {"department": department})
    if tags:
        filters.append({"subcategory": {"$in": list(tags)}})
    if program:
        filters.append({"degree_program": program})
    where = {"$and": filters} if len(filters) > 1 else (filters[0] if filters else None)

    result = col.query(
        query_texts=[query],
        n_results=top_k,
        where=where,
    )
    if not result["ids"] or not result["ids"][0]:
        return []

    hits = []
    for doc_id, doc, meta, distance in zip(
        result["ids"][0], result["documents"][0], result["metadatas"][0], result["distances"][0]
    ):
        # Chroma cosine space: distance = 1 - cosine_similarity
        similarity = max(0.0, 1.0 - float(distance))
        hits.append(
            {
                "text": doc,
                "tag": meta.get("subcategory", ""),
                "score": round(similarity, 4),
                "metadata": meta,
                "source_id": doc_id,
            }
        )
    return hits
