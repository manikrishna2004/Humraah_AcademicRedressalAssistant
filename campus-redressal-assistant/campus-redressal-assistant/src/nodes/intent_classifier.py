"""
Stage 1: State Router & Intent Classifier Node.

Runs the local model (Ollama / Llama 3.1 8B, JSON-constrained -- or the
offline mock in dev mode) to extract routing parameters and decide whether
this turn needs a clarifying question, a gated web search, or can proceed
straight to retrieval.
"""
from __future__ import annotations

from src.llm import get_llm
from src.state import RedressalState


def intent_classifier_node(state: RedressalState) -> dict:
    llm = get_llm()
    result = llm.classify_intent(
        query=state["user_query"], history=state.get("session_history", [])
    )

    missing_fields = result.get("missing_fields", [])
    out_of_domain = result.get("out_of_domain", False)

    if missing_fields:
        route_decision = "clarify_1"
    elif out_of_domain:
        route_decision = "web_search"
    else:
        route_decision = "retrieve"

    return {
        "category": result.get("category"),
        "subcategory": result.get("subcategory"),
        "department": result.get("department"),
        "degree_program": result.get("degree_program"),
        "out_of_domain": out_of_domain,
        "missing_fields": missing_fields,
        "route_decision": route_decision,
    }


def route_after_intent(state: RedressalState) -> str:
    """Conditional edge selector out of Node 1."""
    return state["route_decision"]
