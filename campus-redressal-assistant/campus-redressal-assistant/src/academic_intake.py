"""Browser intake and the academic issue categories shared by both entry paths."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from src.llm import DEPARTMENTS, DEGREE_PROGRAMS

ISSUES = {
    "supplementary_exam": "Supplementary exam",
    "grade_review": "Grade review",
    "mid_sem_review": "Mid-sem answer script",
    "end_sem_appeal": "End-sem grade concern",
    "attendance_waiver": "Attendance waiver",
    "escalation": "Unresponsive advisor",
}

SCENARIOS = (
    {"tag": "supplementary_exam", "query": "I missed the suppli form deadline. What should I do?"},
    {"tag": "grade_review", "query": "How do I ask for a grade review in CSE?"},
    {"tag": "escalation", "query": "My FA in Mech isn't replying. I'm in 4-year B.Tech."},
    {"tag": "attendance_waiver", "query": "How do I request an attendance waiver after being ill?"},
)

_ALIASES = [
    (r"\b(?:suppli(?:es)?|supple(?:mentary)?|back paper)(?:\s+exam(?:ination)?s?)?\b", "supplementary exam"),
    (r"\b(?:cse|comp sci)\b", "Computer Science and Engineering"),
    (r"\bmech\b|(?-i:\bME\b)", "Mechanical Engineering"),
    (r"\bee\b", "Electrical Engineering"),
    (r"\bchem engg?\b", "Chemical Engineering"),
    (r"\bb\s*tech\b|\bbtech\b", "B.Tech"),
    (r"\b(?:dd|dual)\b(?![- ]degree)", "dual degree"),
    (r"(?<!faculty )\b(?:advisor|adviser|fa)\b", "Faculty Advisor"),
    (r"\b(?:grade issue|grade dispute|marks review|grade recheck|recheck my (?:marks|grade))\b", "grade review"),
    (r"\bmid(?:dle)?[- ]?semester\b", "mid-sem"),
    (r"\bend[- ]?semester\b", "end-sem"),
]


class AcademicIntent(BaseModel):
    category: str | None = None
    subcategory: str | None = None
    department: str | None = None
    degree_program: str | None = None
    out_of_domain: bool = False
    missing_fields: list[Literal["department", "degree_program"]] = Field(default_factory=list)


def normalize_query(query: str) -> str:
    for pattern, replacement in _ALIASES:
        query = re.sub(pattern, replacement, query, flags=re.I)
    return query


def validate_intent(raw: dict) -> dict:
    try:
        result = AcademicIntent.model_validate(raw)
    except ValidationError:
        result = AcademicIntent(out_of_domain=True)
    tag = result.subcategory
    if result.out_of_domain or tag not in ISSUES:
        return AcademicIntent(out_of_domain=True).model_dump()

    result.category = "Academic"
    result.department = result.department if result.department in DEPARTMENTS else None
    result.degree_program = result.degree_program if result.degree_program in DEGREE_PROGRAMS else None
    result.missing_fields = []
    if not result.department and tag != "supplementary_exam":
        result.missing_fields.append("department")
    if not result.degree_program and tag in {"attendance_waiver", "escalation"}:
        result.missing_fields.append("degree_program")
    return result.model_dump()
