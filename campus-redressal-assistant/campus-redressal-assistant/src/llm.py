"""
LLM client used by two nodes:
  - Node 1 (Intent Classifier): structured JSON extraction
  - Node 3 (Synthesizer): standardized markdown action-plan generation

LLM_BACKEND=mock    -> deterministic, offline, rule-based stand-in. Lets the
                        rest of the graph (routing, interrupts, retrieval,
                        gating) be exercised and demoed without a GPU.
LLM_BACKEND=ollama  -> real local model (Llama 3.1 8B / Qwen 2.5) served by
                        Ollama, called with format="json" for Node 1.
"""
from __future__ import annotations

import json
import re
from typing import Any

from src.config import settings

DEPARTMENTS = [
    "Computer Science and Engineering",
    "Electrical Engineering",
    "Mechanical Engineering",
    "Civil Engineering",
    "Chemical Engineering",
    "Aerospace Engineering",
    "Metallurgical and Materials Engineering",
]

DEGREE_PROGRAMS = [
    "UG 4-Year B.Tech",
    "UG-PG 5-Year Dual Degree",
    "M.Tech",
    "PhD",
]

# subcategory tags used later for ambiguity detection in the confidence gate
INTENT_RULES: list[tuple[re.Pattern, dict[str, Any]]] = [
    (re.compile(r"\bsupplementary exam", re.I),
     {"category": "Academic", "subcategory": "supplementary_exam"}),
    (re.compile(r"attendance|waiver|shortage", re.I),
     {"category": "Academic", "subcategory": "attendance_waiver"}),
    (re.compile(r"grade review|revaluat|remarking", re.I),
     {"category": "Academic", "subcategory": "grade_review"}),
    (re.compile(r"mid.?sem", re.I),
     {"category": "Academic", "subcategory": "mid_sem_review"}),
    (re.compile(r"end.?sem|grade appeal", re.I),
     {"category": "Academic", "subcategory": "end_sem_appeal"}),
    (re.compile(r"hostel|room allotment|\bmess\b", re.I),
     {"category": "Hostel", "subcategory": "hostel_admin"}),
    (re.compile(r"\bfa\b|faculty advisor|\bhod\b|unresponsive|ignoring|escalat", re.I),
     {"category": "Academic", "subcategory": "escalation"}),
]

OUT_OF_DOMAIN_HINTS = re.compile(
    r"weather|movie|stock price|cricket score|recipe", re.I
)


def _extract_department(query: str) -> str | None:
    for dept in DEPARTMENTS:
        # match on last significant word too, e.g. "civil"
        key_word = dept.split()[0].lower()
        if key_word in query.lower() or dept.lower() in query.lower():
            return dept
    return None


PROGRAM_HINTS = (
    ("UG-PG 5-Year Dual Degree", ("dual degree", "5-year", "5 year")),
    ("UG 4-Year B.Tech", ("b.tech", "4-year", "4 year", "undergrad")),
    ("M.Tech", ("m.tech", "masters")),
    ("PhD", ("phd",)),
)


def _extract_program(query: str) -> str | None:
    query = query.lower()
    for program, hints in PROGRAM_HINTS:
        if any(hint in query for hint in hints):
            return program
    return None


class MockLLM:
    """Deterministic, offline stand-in for the local Ollama model."""

    def classify_intent(self, query: str, history: list[dict[str, str]]) -> dict:
        category, subcategory = None, None
        for pattern, tags in INTENT_RULES:
            if pattern.search(query):
                category, subcategory = tags["category"], tags["subcategory"]
                break

        out_of_domain = bool(OUT_OF_DOMAIN_HINTS.search(query)) or category is None
        department = _extract_department(query)
        degree_program = _extract_program(query)

        missing_fields = []
        # Department/program are only *required* for routing when the query
        # concerns a person/procedure that differs by department (academic
        # escalation, grade review, attendance). Directory-only lookups still
        # need it to disambiguate which HOD/FA to point to.
        if not out_of_domain and category is not None:
            if department is None and subcategory != "supplementary_exam":
                missing_fields.append("department")
            if degree_program is None and subcategory in {"attendance_waiver", "escalation"}:
                missing_fields.append("degree_program")

        return {
            "category": category,
            "subcategory": subcategory,
            "department": department,
            "degree_program": degree_program,
            "out_of_domain": out_of_domain,
            "missing_fields": missing_fields,
        }

    def synthesize(self, prompt: str, context: dict | None = None) -> str:
        # Mock mode never calls a model -- it deterministically renders the
        # standardized markdown template straight from the retrieved
        # context, so the demo is reproducible with no local model running.
        from src.nodes.synthesizer import render_markdown  # local import: avoid cycle

        return render_markdown(context or {})


class OllamaLLM:
    """Production LLM backend: local Llama 3.1 8B / Qwen 2.5 via Ollama."""

    _INTENT_SYSTEM_PROMPT = (
        "You are the intent-classification node of a campus grievance-redressal "
        "assistant. Given the student's query and prior turns, respond with ONLY "
        "a JSON object with exactly these keys: "
        '{"category": str|null, "subcategory": str|null, "department": str|null, '
        '"degree_program": str|null, "out_of_domain": bool, "missing_fields": '
        "[list of field names among 'department', 'degree_program' still needed "
        "to route this query]}. Valid departments: " + ", ".join(DEPARTMENTS) + ". "
        "Valid degree_program values: " + ", ".join(DEGREE_PROGRAMS) + ". "
        "No prose, no markdown fences -- JSON only."
    )

    def __init__(self):
        import ollama  # local import: only required in production mode

        self._client = ollama.Client(host=settings.ollama_host)

    def classify_intent(self, query: str, history: list[dict[str, str]]) -> dict:
        messages = [{"role": "system", "content": self._INTENT_SYSTEM_PROMPT}]
        messages.extend(history)
        messages.append({"role": "user", "content": query})

        response = self._client.chat(
            model=settings.ollama_model,
            messages=messages,
            format="json",
            options={"temperature": 0.0},
        )
        content = response["message"]["content"]
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # Local models occasionally wrap JSON in fences despite instructions.
            cleaned = content.strip().strip("`").removeprefix("json").strip()
            return json.loads(cleaned)

    def synthesize(self, prompt: str, context: dict | None = None) -> str:
        response = self._client.chat(
            model=settings.ollama_model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.2},
        )
        return response["message"]["content"]


_llm_singleton: MockLLM | OllamaLLM | None = None


def get_llm() -> MockLLM | OllamaLLM:
    global _llm_singleton
    if _llm_singleton is None:
        _llm_singleton = OllamaLLM() if settings.llm_backend == "ollama" else MockLLM()
    return _llm_singleton
