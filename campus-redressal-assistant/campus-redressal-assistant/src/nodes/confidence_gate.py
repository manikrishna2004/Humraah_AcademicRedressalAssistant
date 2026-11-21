"""
Confidence & Similarity Gate (threshold = 0.65 by default).

Pure logic node (no LLM call) sitting between the Async Multi-Route
Retriever and the three-way split described in the architecture:

    score >= threshold, single clear path      -> synthesize   (Node 3)
    multiple conflicting routes at/near the top -> clarify_2    (ambiguity)
    score < threshold / missing practical ctx   -> clarify_3    (action-plan)

Two deliberate refinements over a literal reading of the diagram:

1. The Directory Store's "score" is really just presence/absence of a
   contact match (SQL exact match has no notion of similarity), and a
   department contact is available for nearly every query once the
   department is known. Counting it toward the knowledge/confidence score
   would make the gate trivially pass on department alone, regardless of
   whether we actually found a matching procedure. So directory results
   feed the final answer's "Points of Contact" section (see synthesizer.py)
   but not the confidence score.
2. Escalation-type queries ("my FA is unresponsive, should I go to the
   HOD?") always need Clarification Point 3's action-plan question
   (has a formal email already been sent?) to pick the right branch,
   independent of how well-matched the retrieval otherwise is -- that is
   the worked example the architecture itself gives for this checkpoint.
"""
from __future__ import annotations

from src.config import settings
from src.state import RedressalState

# How close two competing hits' scores need to be to count as "conflicting"
# rather than one clearly winning.
_AMBIGUITY_MARGIN = 0.10
# A hit below this is too weak to count as a real competing route -- without
# this floor, several equally-mediocre near-misses would look "ambiguous".
_MIN_SCORE_FOR_AMBIGUITY = 0.30
_WEB_FALLBACK_SCORE = 0.66  # a gated web search result is treated as "just enough" grounding


def confidence_gate_node(state: RedressalState) -> dict:
    threshold = settings.confidence_threshold

    senior_hits = state.get("retrieved_senior_fundae") or []
    rulebook_hits = state.get("retrieved_rules") or []
    senior_top = max((h["score"] for h in senior_hits), default=0.0)
    rulebook_top = max((h["score"] for h in rulebook_hits), default=0.0)
    web_score = _WEB_FALLBACK_SCORE if state.get("web_search_results") else 0.0

    knowledge_score = max(senior_top, rulebook_top, web_score)

    if state.get("guided_resolution"):
        return {"confidence_score": round(knowledge_score, 4), "gate_decision": "synthesize"}

    # --- Clarification Point 3, forced: escalation queries always need to
    # know whether the formal channel was already tried, before Node 3 can
    # pick the initial-contact vs. HOD-escalation branch.
    if state.get("subcategory") == "escalation" and state.get("formal_email_sent") is None:
        return {"confidence_score": round(knowledge_score, 4), "gate_decision": "clarify_3"}

    if state.get("academic_mode"):
        if state.get("subcategory") == "grade_review":
            return {
                "confidence_score": round(knowledge_score, 4),
                "gate_decision": "clarify_2",
                "ambiguous_routes": ["mid_sem_review", "end_sem_appeal"],
            }
        return {"confidence_score": round(knowledge_score, 4), "gate_decision": "synthesize"}

    # --- Clarification Point 2: two or more distinct, genuinely-competitive
    # procedural tags near the top.
    near_top_tags = {
        h["tag"]
        for h in (*senior_hits, *rulebook_hits)
        if h.get("tag")
        and h["score"] >= _MIN_SCORE_FOR_AMBIGUITY
        and h["score"] >= knowledge_score - _AMBIGUITY_MARGIN
    }
    if len(near_top_tags) >= 2:
        return {
            "confidence_score": round(knowledge_score, 4),
            "gate_decision": "clarify_2",
            "ambiguous_routes": sorted(near_top_tags),
        }

    if knowledge_score >= threshold:
        return {"confidence_score": round(knowledge_score, 4), "gate_decision": "synthesize"}

    return {"confidence_score": round(knowledge_score, 4), "gate_decision": "clarify_3"}


def route_after_gate(state: RedressalState) -> str:
    """Conditional edge selector out of the confidence gate."""
    return state["gate_decision"]
