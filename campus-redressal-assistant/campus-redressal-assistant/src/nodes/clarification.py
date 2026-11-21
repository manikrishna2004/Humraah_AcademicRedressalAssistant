"""
The three clarification checkpoints from the architecture, each implemented
with LangGraph's `interrupt()`.

`interrupt()` pauses the graph *inside this node* and hands a payload back
to the caller. The caller resumes later with `Command(resume=<answer>)`,
using the SAME thread_id -- the checkpointer replays only up to this node
and injects the answer directly into state, then the graph's own edges
(defined in graph.py) send execution straight to Node 2 or Node 3. Node 1
(the intent classifier) is never re-run. This is the state-injection /
forward-transition mechanism described in the architecture: no LLM call is
wasted re-classifying what the user already told the system.
"""
from __future__ import annotations

from langgraph.types import interrupt

from src.state import RedressalState

# ---------------------------------------------------------------------------
# Clarification Point 1 -- System-Level Prompt (missing routing entities)
# Resumes directly into Node 2 (Async Multi-Route Retriever).
# ---------------------------------------------------------------------------


def clarification_1_node(state: RedressalState) -> dict:
    missing = state.get("missing_fields", [])
    question = (
        "Which department are you in, and are you in a 4-Year B.Tech or "
        "5-Year Dual Degree program? (This determines your exact Faculty "
        "Advisor and HOD escalation path.)"
        if set(missing) >= {"department", "degree_program"}
        else "Which department are you in? (This determines your exact "
        "Faculty Advisor / HOD escalation path.)"
    )

    answer = interrupt(
        {
            "checkpoint": "clarification_1",
            "question": question,
            "missing_fields": missing,
        }
    )
    # `answer` is expected to be a dict, e.g. {"department": "Civil Engineering",
    # "degree_program": "UG 4-Year B.Tech"} -- injected straight into state.
    update: dict = {"clarification_provided": True}
    if "department" in answer:
        update["department"] = answer["department"]
    if "degree_program" in answer:
        update["degree_program"] = answer["degree_program"]
    return update


# ---------------------------------------------------------------------------
# Clarification Point 2 -- Retrieval Ambiguity (Similarity-Gate boundary)
# Resumes directly into Node 3 (Synthesizer), with irrelevant chunks dropped.
# ---------------------------------------------------------------------------


def clarification_2_node(state: RedressalState) -> dict:
    routes = state.get("ambiguous_routes", [])
    question = (
        f"I found more than one matching procedure: {', '.join(routes)}. "
        "Which one matches what you need?"
    )
    if state.get("academic_mode"):
        question = "Which grade concern are you trying to resolve?"

    chosen = interrupt(
        {
            "checkpoint": "clarification_2",
            "question": question,
            "options": routes,
        }
    )
    # `chosen` is expected to be one of `routes`.
    filtered_senior = [
        h for h in state.get("retrieved_senior_fundae", []) if h.get("tag") == chosen
    ]
    filtered_rules = [h for h in state.get("retrieved_rules", []) if h.get("tag") == chosen]
    if state.get("academic_mode"):
        return {
            "ambiguity_resolved": chosen,
            "retrieved_senior_fundae": filtered_senior,
            "retrieved_rules": filtered_rules,
        }

    return {
        "ambiguity_resolved": chosen,
        # only overwrite if the filter actually kept something, so we never
        # discard the only context we have due to a tagging mismatch
        "retrieved_senior_fundae": filtered_senior or state.get("retrieved_senior_fundae", []),
        "retrieved_rules": filtered_rules or state.get("retrieved_rules", []),
    }


# ---------------------------------------------------------------------------
# Clarification Point 3 -- Action-Plan Context (inside Node 3's boundary)
# Resumes directly into Node 3 (Synthesizer) to pick the right escalation tier.
# ---------------------------------------------------------------------------


def clarification_3_node(state: RedressalState) -> dict:
    question = (
        "Have you already sent a formal email (with an '[Urgent]' tag) and "
        "waited 48 hours? If yes, I'll give you the HOD escalation steps; "
        "if not, here's the initial email template to send first."
    )
    if state.get("academic_mode") == "campus":
        question = "Have you already emailed your faculty advisor about this issue?"

    sent = interrupt(
        {
            "checkpoint": "clarification_3",
            "question": question,
            "options": ["yes", "no"],
        }
    )
    formal_email_sent = str(sent).strip().lower() in {"yes", "true", "y"}
    return {"formal_email_sent": formal_email_sent}
