"""Compose the browser's cited plan from the issue and its matching records."""
from __future__ import annotations

import re

from src.academic_intake import ISSUES
from src.state import RedressalState, RetrievedChunk

ACADEMICS = "https://www.iitkgp.ac.in/navpage/academics"
ERP = "https://erp.iitkgp.ac.in/"
HANDBOOK = "https://student.iitkgp.ac.in/docs/STUDENTCOPY_FACULTYADVISOR_IITKGP.pdf"

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

PRIMARY_CONTACTS = {
    "supplementary_exam": ("Academic Section · UG", "View the institute’s Academic Section listing.", f"{HANDBOOK}#page=8"),
    "grade_review": ("Course instructor", "Find your instructor through your department.", ACADEMICS),
    "mid_sem_review": ("Course instructor", "Look up your instructor in ERP or through your department.", ACADEMICS),
    "end_sem_appeal": ("Course instructor", "Start with the person responsible for the course.", ACADEMICS),
    "attendance_waiver": ("Faculty advisor", "Find your assigned advisor in ERP and confirm the relevant procedure.", ERP),
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
    source_id = hit.get("source_id", "")
    number = source_id.removeprefix("senior-")
    label = f"Sample senior account {int(number) + 1}" if number.isdecimal() else "Sample senior account"
    return {"text": hit["text"], "label": label}


def academic_plan(state: RedressalState) -> dict:
    is_sample = state["academic_mode"] == "sample"
    tag = state.get("ambiguity_resolved") or state.get("subcategory")
    department = state.get("department")
    rules = [_rule(hit) for hit in state.get("retrieved_rules", [])][:3]
    senior = state.get("retrieved_senior_fundae", [])[:2]
    tips = [_tip(hit) for hit in senior]
    notices = []
    contacts = []
    supported = bool(tag and tag in ISSUES)
    sent = state.get("formal_email_sent")

    if supported:
        next_step = NEXT_STEPS.get(tag)
        if tag == "escalation":
            if is_sample:
                next_step = (
                    "In this example, forward the earlier email to the Head of Department and ask for help resolving the issue."
                    if sent else
                    "In this example, email your faculty advisor first. Include the course code, what happened and the deadline."
                )
                role = "HOD" if sent else "Faculty Advisor"
            else:
                next_step = (
                    "Forward your original thread to your department office and ask who can take up the issue. "
                    "Include any upcoming deadline."
                    if sent else
                    "Email your assigned faculty advisor with the course code, the issue and any upcoming deadline."
                )
                role = "Department office" if sent else "Faculty advisor"
                contacts = [{"role": role, "detail": "Find current contacts in the institute directory.", "url": ACADEMICS}]
        else:
            role = "Faculty Advisor" if tag == "attendance_waiver" else None
            title, detail, url = PRIMARY_CONTACTS[tag]
            contacts = [{"role": title, "detail": detail, "url": url}]
            if tag == "supplementary_exam" and not is_sample:
                contacts[0]["email"] = "arug@adm.iitkgp.ac.in"

        if is_sample and role:
            matches = [row for row in state.get("retrieved_directory", []) if row["role"] == role]
            if matches:
                contacts = [{**row, "detail": "Sample directory record"} for row in matches]
        if tag == "escalation" and sent is None:
            next_step = (
                "If you haven't emailed your advisor, send a short note with the course code and deadline. "
                "If you've already emailed and need a reply, ask your department office who can help."
            )
            contacts = []
        if not contacts:
            contacts = [{"role": "Department office", "detail": "Use the academic unit directory to find the current contact.", "url": ACADEMICS}]

        for hit in (*state.get("retrieved_rules", [])[:3], *senior):
            difference = hit.get("metadata", {}).get("policy_difference")
            if difference and rules:
                notices.append({"title": "Sources give different instructions", "text": difference})

        if not rules or state.get("confidence_score", 0) < 0.35:
            notices.append({
                "title": "Limited source coverage",
                "text": "Confirm the applicable procedure and deadlines with the contact below.",
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
