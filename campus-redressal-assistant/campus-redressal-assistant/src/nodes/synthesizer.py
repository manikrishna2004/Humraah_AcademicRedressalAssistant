"""
RAG Context Synthesizer (Node 3) -- the terminal node.

Fuses retrieved SQL contact entries, senior-experience notes and rulebook
policy chunks (plus any clarification answers already injected into state)
into the standardized markdown Action Plan.

LLM_BACKEND=mock   -> deterministic template rendering, no model call.
LLM_BACKEND=ollama -> the same context bundle is handed to the local model
                       as a grounded generation prompt.
"""
from __future__ import annotations

from src.llm import get_llm
from src.state import RedressalState

# Chunks scoring below this are too weak to be worth showing in the final
# answer -- reused by scripts/evaluate.py's groundedness check so the eval
# harness and the renderer agree on what "shown" means.
_MIN_ITEM_SCORE = 0.35

_TEMPLATE_INSTRUCTIONS = """\
You are the response synthesizer for a campus grievance-redressal assistant.
Using ONLY the context provided below, produce the final answer in EXACTLY
this markdown structure:

**Direct Summary**
[A concise 2-sentence summary directly addressing the student's problem.]

**1. Official Academic Policy & Redressal Route**
- Step 1: Formal communication path (email templates, office hours).
- Step 2: Escalation timeline and rulebook reference.

**2. Senior Insights & Practical Navigation (From Experience Data)**
- Practical tips on office timings, communication tone, and common pitfalls.

**3. Relevant Points of Contact**
- Department Student Rep: [Name, Email, Contact]
- Responsible Authority / Office: [Office Location, Office Hours, Designation]

If a section has no supporting context, say so plainly rather than inventing
details.
"""


def _build_context_bundle(state: RedressalState) -> dict:
    return {
        "user_query": state.get("user_query", ""),
        "category": state.get("category"),
        "subcategory": state.get("subcategory"),
        "department": state.get("department"),
        "degree_program": state.get("degree_program"),
        "directory": state.get("retrieved_directory", []),
        "senior_fundae": state.get("retrieved_senior_fundae", []),
        "rules": state.get("retrieved_rules", []),
        "web_results": state.get("web_search_results", []),
        "ambiguity_resolved": state.get("ambiguity_resolved"),
        "formal_email_sent": state.get("formal_email_sent"),
    }


def _build_prompt(bundle: dict) -> str:
    lines = [_TEMPLATE_INSTRUCTIONS, "\n---- CONTEXT ----"]
    lines.append(f"Student query: {bundle['user_query']}")
    lines.append(f"Category / Subcategory: {bundle['category']} / {bundle['subcategory']}")
    lines.append(f"Department: {bundle['department']}  |  Program: {bundle['degree_program']}")
    if bundle["ambiguity_resolved"]:
        lines.append(f"Resolved procedure (user picked): {bundle['ambiguity_resolved']}")
    if bundle["formal_email_sent"] is not None:
        lines.append(f"Already sent formal '[Urgent]' email and waited 48h: {bundle['formal_email_sent']}")

    lines.append("\nDirectory contacts:")
    for d in bundle["directory"]:
        lines.append(f"  - {d}")

    lines.append("\nSenior experience notes:")
    for s in bundle["senior_fundae"]:
        lines.append(f"  - (score={s.get('score')}) {s.get('text')}")

    lines.append("\nRulebook excerpts:")
    for r in bundle["rules"]:
        lines.append(f"  - (score={r.get('score')}) {r.get('text')}")

    if bundle["web_results"]:
        lines.append("\nWeb search fallback results:")
        for w in bundle["web_results"]:
            lines.append(f"  - {w.get('title')}: {w.get('snippet')} ({w.get('url')})")

    return "\n".join(lines)


def render_markdown(bundle: dict) -> str:
    """Deterministic template renderer used by MockLLM (and as a readable
    reference for what the production Ollama call is grounded on)."""
    directory = bundle.get("directory", [])
    # Show only the strongest few matches per section, and drop anything too
    # weak to be a genuine match -- the retriever fetches top_k candidates
    # for the confidence gate to reason over, but the final answer should
    # read like a focused action plan, not a dump of every retrieved chunk.
    senior = sorted(
        (h for h in bundle.get("senior_fundae", []) if h.get("score", 0) >= _MIN_ITEM_SCORE),
        key=lambda h: h.get("score", 0),
        reverse=True,
    )[:3]
    rules = sorted(
        (h for h in bundle.get("rules", []) if h.get("score", 0) >= _MIN_ITEM_SCORE),
        key=lambda h: h.get("score", 0),
        reverse=True,
    )[:3]
    web = bundle.get("web_results", [])

    summary = (
        f"You're asking about a {bundle.get('subcategory') or bundle.get('category') or 'campus'} "
        f"issue in {bundle.get('department') or 'your department'}. "
        + (
            f"You indicated the '{bundle['ambiguity_resolved']}' procedure applies. "
            if bundle.get("ambiguity_resolved")
            else ""
        )
        + (
            "Here is the escalation path, since you've already tried the formal channel."
            if bundle.get("formal_email_sent")
            else "Here is the official path plus what seniors say actually works."
        )
    )

    policy_lines = (
        [f"- {r['text']}" for r in rules]
        if rules
        else ["- No matching rulebook clause was retrieved for this query."]
    )
    senior_lines = (
        [f"- {s['text']}" for s in senior]
        if senior
        else ["- No senior-experience notes were retrieved for this query."]
    )
    if web:
        senior_lines.append(
            "- (Gated web search) " + "; ".join(f"{w['title']} - {w['snippet']}" for w in web)
        )

    contact_lines = []
    for d in directory:
        role = d.get("role", "Contact")
        contact_lines.append(
            f"- {role}: {d.get('name', 'N/A')}, {d.get('email', 'N/A')}, "
            f"{d.get('office') or d.get('contact') or 'N/A'}"
        )
    if not contact_lines:
        contact_lines = ["- No directory contact matched this department."]

    return (
        "**Direct Summary**\n"
        f"{summary}\n\n"
        "**1. Official Academic Policy & Redressal Route**\n"
        + "\n".join(policy_lines)
        + "\n\n"
        "**2. Senior Insights & Practical Navigation (From Experience Data)**\n"
        + "\n".join(senior_lines)
        + "\n\n"
        "**3. Relevant Points of Contact**\n" + "\n".join(contact_lines)
    )


def synthesizer_node(state: RedressalState) -> dict:
    llm = get_llm()
    bundle = _build_context_bundle(state)
    prompt = _build_prompt(bundle)
    final_response = llm.synthesize(prompt, bundle)
    return {"final_response": final_response}
