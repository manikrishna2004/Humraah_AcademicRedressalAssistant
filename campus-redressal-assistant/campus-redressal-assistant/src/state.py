"""
RedressalState -- the single state object threaded through every node in
the graph. LangGraph persists this via a checkpointer keyed on thread_id,
which is what lets a clarification answer be *injected* into the existing
state and resume mid-graph instead of re-running the whole pipeline.
"""
from __future__ import annotations

from typing import Any, Literal, Optional, TypedDict


class DirectoryHit(TypedDict, total=False):
    name: str
    role: str
    department: str
    email: str
    office: str
    office_hours: str


class RetrievedChunk(TypedDict, total=False):
    text: str
    tag: str  # subcategory / procedure tag, used for ambiguity detection
    score: float
    metadata: dict
    source_id: str


RouteDecision = Literal["clarify_1", "web_search", "retrieve", "unsupported"]
GateDecision = Literal["synthesize", "clarify_2", "clarify_3"]


class RedressalState(TypedDict, total=False):
    # --- input / conversation ---
    user_query: str
    session_history: list[dict[str, str]]
    turn_count: int
    academic_mode: Literal["campus", "sample"]

    # --- Node 1: intent classification ---
    category: Optional[str]
    subcategory: Optional[str]
    department: Optional[str]
    degree_program: Optional[str]
    out_of_domain: bool
    missing_fields: list[str]
    route_decision: RouteDecision

    # --- clarification bookkeeping ---
    clarification_provided: bool
    ambiguous_routes: list[str]
    ambiguity_resolved: Optional[str]
    formal_email_sent: Optional[bool]

    # --- web search (gated fallback) ---
    web_search_results: list[dict[str, Any]]

    # --- Node 2: multi-store retrieval ---
    retrieved_directory: list[DirectoryHit]
    retrieved_senior_fundae: list[RetrievedChunk]
    retrieved_rules: list[RetrievedChunk]

    # --- confidence gate ---
    confidence_score: float
    gate_decision: GateDecision

    # --- Node 3: synthesis ---
    final_response: Optional[str]
    action_plan: dict[str, Any]
