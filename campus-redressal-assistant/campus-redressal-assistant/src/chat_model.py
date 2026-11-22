"""Validated model contract for the per-turn web conversation."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationInfo, field_validator

Issue = Literal[
    "supplementary_exam", "grade_review", "mid_sem_review", "end_sem_appeal",
    "attendance_waiver", "escalation", "other",
]
Intent = Literal["describe", "switch", "draft", "contact", "visit", "deadline", "source", "no_reply", "thanks"]
Program = Literal["UG 4-Year B.Tech", "UG-PG 5-Year Dual Degree", "M.Tech", "PhD"]
Slot = Literal["issue", "department", "cohort", "deadline", "actions_taken"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CohortMention(StrictModel):
    program: Program | None
    admission_year: Annotated[int, Field(ge=1900, le=2100)] | None


class DeadlineMention(StrictModel):
    raw: Annotated[str, StringConstraints(min_length=1, max_length=160)]
    urgent: bool


class StudentAction(StrictModel):
    kind: Literal["emailed_advisor", "advisor_no_reply"]
    value: bool
    source: Literal["stated", "inferred"]


class TurnInterpretation(StrictModel):
    intent: Intent
    issues: list[Issue] = Field(max_length=6)
    department: str | None
    cohort: CohortMention | None
    deadline: DeadlineMention | None
    actions: list[StudentAction] = Field(max_length=2)
    corrections: list[Slot] = Field(max_length=5)
    pending_answer: str | None

    @field_validator("department")
    @classmethod
    def directory_department(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is not None and value not in (info.context or {}).get("departments", ()):
            raise ValueError("Department is absent from the directory")
        return value
