"""
Async Multi-Route Retriever (Node 2).

Fires the three stores concurrently with asyncio.gather():
    - Directory Store         (SQLite, deterministic SQL exact match)
    - Senior Experience Store (ChromaDB Col. A, dense cosine similarity)
    - Official Rulebook Store (ChromaDB Col. B, hybrid BM25 + vector RRF)

Reached from three different upstream edges (valid query, clarification-1
resolved, or gated web search already run) -- in every case it re-uses
whatever `department` / `degree_program` / `user_query` is already sitting
in state rather than re-deriving it, which is the whole point of the
state-injection continuation design.
"""
from __future__ import annotations

import asyncio

from src.academic_intake import normalize_query
from src.config import settings
from src.state import RedressalState
from src.stores import campus_directory, directory_store, rulebook_store, senior_experience_store


async def retriever_node(state: RedressalState) -> dict:
    query = state["user_query"]
    department = state.get("department")
    top_k = settings.top_k
    mode = state.get("academic_mode")
    tag = state.get("subcategory")
    tags = ()
    if mode and tag:
        query = normalize_query(query)
        tags = ("mid_sem_review", "end_sem_appeal") if tag == "grade_review" and not state.get("guided_resolution") else (tag,)

    if mode == "campus":
        directory_task = asyncio.to_thread(
            campus_directory.academic_contacts, tag, department, state.get("formal_email_sent")
        )
        senior_task = asyncio.to_thread(
            senior_experience_store.query_senior_experience, query, department, top_k, tags=tags, campus=True
        )
    else:
        directory_task = asyncio.to_thread(directory_store.query_directory, department)
        senior_task = asyncio.to_thread(
            senior_experience_store.query_senior_experience, query, department, top_k,
            tags=tags, program=state.get("degree_program") if mode else None,
        )
    rulebook_task = asyncio.to_thread(
        rulebook_store.query_rulebook, query, department, top_k, tags=tags, dataset=mode
    )

    directory_hits, senior_hits, rulebook_hits = await asyncio.gather(
        directory_task, senior_task, rulebook_task
    )

    return {
        "retrieved_directory": directory_hits,
        "retrieved_senior_fundae": senior_hits,
        "retrieved_rules": rulebook_hits,
    }
