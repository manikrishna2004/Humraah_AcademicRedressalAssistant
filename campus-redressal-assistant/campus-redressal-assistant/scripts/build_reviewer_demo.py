"""Export a self-contained browser build for a public prototype review."""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.academic_intake import ISSUES, SCENARIOS, _ALIASES
from src.academic_plan import academic_plan
from src.llm import DEPARTMENTS, DEGREE_PROGRAMS, INTENT_RULES, OUT_OF_DOMAIN_HINTS, PROGRAM_HINTS


def load_sources():
    data = ROOT / "data"
    sample_rules = json.loads((data / "rulebook_chunks.json").read_text())
    campus_rules = json.loads((data / "campus_sources.json").read_text())
    rules = {
        "sample": [
            {"text": row["text"], "metadata": row} for row in sample_rules
        ],
        "campus": [
            {"text": row["text"], "metadata": row} for row in campus_rules
        ],
    }
    tips = [
        {"text": row["summary"], "metadata": row, "source_id": f"senior-{index}"}
        for index, row in enumerate(json.loads((data / "senior_experiences.json").read_text()))
    ]
    with (data / "faculty_directory.csv").open(newline="", encoding="utf-8") as file:
        directory = list(csv.DictReader(file))
    return rules, tips, directory


def export_plans():
    rules, tips, directory = load_sources()
    templates = []
    template_ids = {}
    index = {}
    issues = [tag for tag in ISSUES if tag != "grade_review"]

    for mode, tag, dept, program in itertools.product(
        rules, issues, ("", *DEPARTMENTS), ("", *DEGREE_PROGRAMS),
    ):
        selected_rules = [
            hit for hit in rules[mode]
            if hit["metadata"]["subcategory"] == tag
            and hit["metadata"]["department"] in {"General", dept}
        ]
        selected_tips = [
            hit for hit in tips
            if mode == "sample"
            and hit["metadata"]["subcategory"] == tag
            and hit["metadata"]["department"] == dept
            and (not program or hit["metadata"]["degree_program"] == program)
        ]
        selected_contacts = [
            contact for contact in directory
            if mode == "sample" and contact["department"] == dept
        ]
        for sent in ("yes", "no") if tag == "escalation" else ("",):
            plan = academic_plan({
                "academic_mode": mode,
                "subcategory": tag,
                "formal_email_sent": sent == "yes",
                "retrieved_rules": selected_rules,
                "retrieved_senior_fundae": selected_tips,
                "retrieved_directory": selected_contacts,
                "confidence_score": 1 if selected_rules else 0,
            })
            plan.pop("department")
            serialized = json.dumps(plan, sort_keys=True)
            if serialized not in template_ids:
                template_ids[serialized] = len(templates)
                templates.append(plan)
            index["|".join((mode, tag, dept, program, sent))] = template_ids[serialized]

    return index, templates


def build(output: Path):
    output.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "app.js", "style.css"):
        shutil.copyfile(ROOT / "web" / name, output / name)
    shutil.copyfile(ROOT / "deployment" / "reviewer_transport.mjs", output / "transport.js")

    page = output / "index.html"
    html = page.read_text()
    html = html.replace(
        '<span class="helper">Leave out names and roll numbers.</span>',
        '<span class="helper">Your question stays in this tab.</span>',
    )
    page.write_text(html)

    index, templates = export_plans()
    data = {
        "issues": ISSUES,
        "scenarios": [{**scenario, "label": ISSUES[scenario["tag"]]} for scenario in SCENARIOS],
        "aliases": [[r"\bME\b", "Mechanical Engineering", "g"]]
        + [[pattern, replacement, "gi"] for pattern, replacement in _ALIASES],
        "intents": [[pattern.pattern, tags["subcategory"]] for pattern, tags in INTENT_RULES],
        "outOfDomain": OUT_OF_DOMAIN_HINTS.pattern,
        "departments": DEPARTMENTS,
        "degreePrograms": DEGREE_PROGRAMS,
        "programHints": PROGRAM_HINTS,
        "fallback": academic_plan({"academic_mode": "campus"}),
        "index": index,
        "plans": templates,
    }
    (output / "demo-data.json").write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    build(parser.parse_args().output)
