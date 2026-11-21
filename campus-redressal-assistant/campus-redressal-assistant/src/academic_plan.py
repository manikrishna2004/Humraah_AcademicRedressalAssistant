"""Compose the browser's cited plan from the issue and its matching records."""
from __future__ import annotations

import re

from src.academic_intake import ISSUES
from src.state import RedressalState, RetrievedChunk

NEXT_STEPS = {
    "supplementary_exam": (
        "Check the supplementary exam notice in ERP. If the application window has closed, "
        "ask the Academic Section whether late registration is available for your batch."
    ),
    "grade_review": (
        "Ask your instructor to explain the grade or mark you’re concerned about. Include the course code "
        "and which assessment you mean. They can confirm whether viewing the script or requesting a review applies."
    ),
    "mid_sem_review": (
        "Ask the course instructor when you can view your evaluated answer script. "
        "Include the course code and the exam date."
    ),
    "end_sem_appeal": (
        "Ask the course instructor to check the specific discrepancy. If it remains unresolved, "
        "confirm the grade revision procedure for your batch with the Academic Section."
    ),
    "attendance_waiver": (
        "Ask your faculty advisor which attendance or medical-leave procedure applies to your "
        "course and batch. Confirm the accepted documents and deadline before submitting."
    ),
}

def _rule(hit: RetrievedChunk) -> dict:
    text = hit["text"]
    metadata = hit.get("metadata", {})
    sample_clause = re.match(r"Clause [\d.]+", text)
    label = metadata.get("source_label") or (
        f"Sample rulebook · {sample_clause.group()}" if sample_clause else "Sample rulebook"
    )
    return {"text": text, "label": label, "url": metadata.get("source_url") or None}


def _tip(hit: RetrievedChunk) -> dict:
    return {"text": hit["text"], "label": "Fictional example for the prototype"}


def academic_plan(state: RedressalState) -> dict:
    tag = state.get("ambiguity_resolved") or state.get("subcategory")
    department = state.get("department")
    rules = [_rule(hit) for hit in state.get("retrieved_rules", [])][:3]
    tips = [_tip(hit) for hit in state.get("retrieved_senior_fundae", [])[:2]]
    notices = []
    contacts = state.get("retrieved_directory", [])
    supported = bool(tag and tag in ISSUES)
    sent = state.get("formal_email_sent")

    if supported:
        next_step = NEXT_STEPS.get(tag)
        if tag == "escalation":
            if sent is True:
                next_step = "Forward your original email to your department office and ask who can take up the issue. Include any upcoming deadline."
            elif sent is False:
                next_step = "Email your assigned faculty advisor with the course code, the issue and any upcoming deadline."
            else:
                next_step = (
                    "If you haven't emailed your advisor, send a short note with the course code and deadline. "
                    "If you've already emailed and need a reply, ask your department office who can help."
                )

        for rule in state.get("retrieved_rules", [])[:3]:
            difference = rule.get("metadata", {}).get("policy_difference")
            if difference:
                notices.append({"title": "Sources give different instructions", "text": difference})

        if not rules:
            notices.append({
                "title": "Confirm the procedure",
                "text": "Ask the listed contact which rule and deadline apply to your case.",
            })
    else:
        next_step = (
            "Humraah covers supplementary exams, grade reviews, attendance waivers and advisor follow-ups. "
            "Choose one of the guided topics or describe the academic issue you need help with."
        )

    return {
        "issue": ISSUES.get(tag, "Choose an academic issue"),
        "department": department,
        "next_step": next_step,
        "rules": rules,
        "tips": tips,
        "contacts": contacts,
        "notices": notices,
        "supported": supported,
    }
