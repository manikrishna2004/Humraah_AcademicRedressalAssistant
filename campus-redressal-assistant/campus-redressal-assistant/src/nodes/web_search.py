"""
Gated Web Search Node.

Only reached when Node 1 flags the query as completely out-of-domain / no
local context expected. Gated behind the confidence threshold conceptually:
its results are merged into state and still flow through the Async
Multi-Route Retriever + Confidence Gate rather than short-circuiting
straight to an answer, so a locally-known fact always wins over the web.
"""
from __future__ import annotations

from src.config import settings
from src.state import RedressalState


def _mock_search(query: str, max_results: int) -> list[dict]:
    return [
        {
            "title": f"[mock result] General information related to: {query}",
            "snippet": (
                "Web search is running in mock mode (WEB_SEARCH_BACKEND=mock). "
                "Switch to duckduckgo in .env for real results."
            ),
            "url": "https://example.com/mock-result",
        }
        for _ in range(min(1, max_results))
    ]


def _duckduckgo_search(query: str, max_results: int) -> list[dict]:
    from duckduckgo_search import DDGS  # local import: only needed in production mode

    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=max_results))
    return [
        {"title": r.get("title", ""), "snippet": r.get("body", ""), "url": r.get("href", "")}
        for r in results
    ]


def web_search_node(state: RedressalState) -> dict:
    query = state["user_query"]
    max_results = settings.web_search_max_results

    if settings.web_search_backend == "duckduckgo":
        results = _duckduckgo_search(query, max_results)
    else:
        results = _mock_search(query, max_results)

    return {"web_search_results": results}
