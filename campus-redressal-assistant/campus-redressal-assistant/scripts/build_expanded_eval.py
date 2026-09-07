"""
Builds a larger, paraphrase-expanded evaluation set from the existing
sample senior-experience records and rulebook clauses, following the
"canonical case -> paraphrased queries" methodology: each real record in
data/senior_experiences.json / data/rulebook_chunks.json becomes several
naturally-phrased query variants, testing whether the pipeline understands
the underlying request rather than matching one fixed keyword set.

Paraphrases were written to sound like a real student asking, NOT
engineered to deliberately dodge or hit the intent classifier's keyword
patterns in src/llm.py -- so failures found this way are honest signal
about paraphrase robustness, not a rigged test.

Output: eval/test_queries_expanded.json
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "eval" / "test_queries_expanded.json"

# Each block: (subcategory, department, program_or_None, [query templates])
BLOCKS = [
    ("attendance_waiver", "Civil Engineering", "UG 4-Year B.Tech", [
        "I need an attendance waiver for {dept}, {prog}.",
        "How do I request a waiver for my attendance shortfall? I'm in {dept}, {prog}.",
        "My attendance is low and I need it excused - {dept} student, {prog}.",
        "What's the process to get my attendance condoned? {dept}, {prog}.",
    ]),
    ("attendance_waiver", "Computer Science and Engineering", "UG 4-Year B.Tech", [
        "I need an attendance waiver for {dept}, {prog}.",
        "How do I request a waiver for my attendance shortfall? I'm in {dept}, {prog}.",
        "My attendance is low and I need it excused - {dept} student, {prog}.",
        "What's the process to get my attendance condoned? {dept}, {prog}.",
    ]),
    ("attendance_waiver", "Mechanical Engineering", "UG-PG 5-Year Dual Degree", [
        "I need an attendance waiver for {dept}, {prog}.",
        "How do I request a waiver for my attendance shortfall? I'm in {dept}, {prog}.",
        "My attendance is low and I need it excused - {dept} student, {prog}.",
        "What's the process to get my attendance condoned? {dept}, {prog}.",
    ]),
    ("attendance_waiver", "Electrical Engineering", "UG 4-Year B.Tech", [
        "I need an attendance waiver for {dept}, {prog}.",
        "How do I request a waiver for my attendance shortfall? I'm in {dept}, {prog}.",
        "My attendance is low and I need it excused - {dept} student, {prog}.",
        "What's the process to get my attendance condoned? {dept}, {prog}.",
    ]),
    ("mid_sem_review", "Computer Science and Engineering", None, [
        "How can I see my mid-semester answer script in {dept}?",
        "What's the process to check my midsem paper, {dept}?",
        "Can I review my Mid Sem exam script with my professor? {dept}.",
        "I want to look at my midterm answer sheet - {dept} student.",
    ]),
    ("mid_sem_review", "Civil Engineering", None, [
        "How can I see my mid-semester answer script in {dept}?",
        "What's the process to check my midsem paper, {dept}?",
        "Can I review my Mid Sem exam script with my professor? {dept}.",
        "I want to look at my midterm answer sheet - {dept} student.",
    ]),
    ("end_sem_appeal", "Computer Science and Engineering", None, [
        "How do I file an end-semester grade appeal in {dept}?",
        "What's the process for appealing my final grade, {dept} student?",
        "I disagree with my semester grade and want to appeal - {dept}.",
        "How do I submit a grade appeal form for {dept}?",
    ]),
    ("end_sem_appeal", "Mechanical Engineering", None, [
        "How do I file an end-semester grade appeal in {dept}?",
        "What's the process for appealing my final grade, {dept} student?",
        "I disagree with my semester grade and want to appeal - {dept}.",
        "How do I submit a grade appeal form for {dept}?",
    ]),
    ("hostel_admin", "Mechanical Engineering", None, [
        "How do I get a hostel room reallocation? {dept} student.",
        "I want to switch to a different hostel room - {dept}.",
        "Can I request a room change within my hostel? {dept}.",
        "My roommate situation isn't working out, can I move rooms? {dept}.",
    ]),
    ("hostel_admin", "Civil Engineering", None, [
        "How do I get a hostel room reallocation? {dept} student.",
        "I want to switch to a different hostel room - {dept}.",
        "Can I request a room change within my hostel? {dept}.",
        "My roommate situation isn't working out, can I move rooms? {dept}.",
    ]),
    ("hostel_admin", "Computer Science and Engineering", None, [
        "How do I get a hostel room reallocation? {dept} student.",
        "I want to switch to a different hostel room - {dept}.",
        "Can I request a room change within my hostel? {dept}.",
        "My roommate situation isn't working out, can I move rooms? {dept}.",
    ]),
    ("escalation", "Civil Engineering", "UG 4-Year B.Tech", [
        "My FA is unresponsive, should I go to the HOD? {dept}, {prog}.",
        "My faculty advisor hasn't replied to my last three emails. {dept}, {prog}.",
        "It's been over a week and my advisor still hasn't responded - what should I do? {dept}, {prog}.",
        "I don't think my advisor is going to reply - who else can I contact? {dept}, {prog}.",
    ]),
    ("escalation", "Electrical Engineering", "UG 4-Year B.Tech", [
        "My FA is unresponsive, should I go to the HOD? {dept}, {prog}.",
        "My faculty advisor hasn't replied to my last three emails. {dept}, {prog}.",
        "It's been over a week and my advisor still hasn't responded - what should I do? {dept}, {prog}.",
        "I don't think my advisor is going to reply - who else can I contact? {dept}, {prog}.",
    ]),
    ("escalation", "Mechanical Engineering", "UG 4-Year B.Tech", [
        "My FA is unresponsive, should I go to the HOD? {dept}, {prog}.",
        "My faculty advisor hasn't replied to my last three emails. {dept}, {prog}.",
        "It's been over a week and my advisor still hasn't responded - what should I do? {dept}, {prog}.",
        "I don't think my advisor is going to reply - who else can I contact? {dept}, {prog}.",
    ]),
    ("escalation", "Computer Science and Engineering", "UG 4-Year B.Tech", [
        "My FA is unresponsive, should I go to the HOD? {dept}, {prog}.",
        "My faculty advisor hasn't replied to my last three emails. {dept}, {prog}.",
        "It's been over a week and my advisor still hasn't responded - what should I do? {dept}, {prog}.",
        "I don't think my advisor is going to reply - who else can I contact? {dept}, {prog}.",
    ]),
]

AMBIGUOUS_GRADE_REVIEW = [
    "How do I apply for a grade review in {dept}?",
    "I want my exam re-checked, what's the process in {dept}?",
    "Can I get my paper re-evaluated in {dept}?",
]

OUT_OF_DOMAIN = [
    "What's the weather like today?",
    "Can you recommend a good movie to watch tonight?",
    "What's the cricket score right now?",
]

MISSING_ENTITY = [
    "My advisor is ignoring my attendance waiver request.",
    "I want to request an attendance waiver but don't know who to contact.",
    "Someone please help me with an attendance shortage issue.",
]


def main():
    cases = []
    idx = 1

    for subcategory, dept, prog, templates in BLOCKS:
        is_escalation = subcategory == "escalation"
        for template in templates:
            query = template.format(dept=dept, prog=prog or "")
            cases.append({
                "id": f"ex{idx:03d}",
                "query": query,
                "resume_answers": ["yes"] if is_escalation else [],
                "expected": {
                    "route_decision": "retrieve",
                    "department": dept,
                    "subcategory": subcategory,
                    "gate_decision": "clarify_3" if is_escalation else "synthesize",
                    "top_tag": subcategory,
                    "is_escalation": is_escalation,
                },
                "note": f"Paraphrase-expansion probe for {subcategory}/{dept}",
                "source": "paraphrase_expansion",
            })
            idx += 1

    for dept in ["Computer Science and Engineering"]:
        for template in AMBIGUOUS_GRADE_REVIEW:
            query = template.format(dept=dept)
            for resume, top_tag in [("mid_sem_review", "mid_sem_review"), ("end_sem_appeal", "end_sem_appeal")]:
                cases.append({
                    "id": f"ex{idx:03d}",
                    "query": query,
                    "resume_answers": [resume],
                    "expected": {
                        "route_decision": "retrieve",
                        "department": dept,
                        "subcategory": "grade_review",
                        "gate_decision": "clarify_2",
                        "top_tag": top_tag,
                        "is_escalation": False,
                    },
                    "note": "Ambiguity probe (grade review), paraphrase variant",
                    "source": "paraphrase_expansion",
                })
                idx += 1

    for query in OUT_OF_DOMAIN:
        cases.append({
            "id": f"ex{idx:03d}",
            "query": query,
            "resume_answers": [],
            "expected": {
                "route_decision": "web_search",
                "department": None,
                "subcategory": None,
                "gate_decision": "synthesize",
                "top_tag": None,
                "is_escalation": False,
            },
            "note": "Out-of-domain probe",
            "source": "paraphrase_expansion",
        })
        idx += 1

    for query in MISSING_ENTITY:
        cases.append({
            "id": f"ex{idx:03d}",
            "query": query,
            "resume_answers": [{"department": "Civil Engineering", "degree_program": "UG 4-Year B.Tech"}],
            "expected": {
                "route_decision": "clarify_1",
                "department": "Civil Engineering",
                "subcategory": "attendance_waiver",
                "gate_decision": "synthesize",
                "top_tag": "attendance_waiver",
                "is_escalation": False,
            },
            "note": "Missing-entity clarification probe, paraphrase variant",
            "source": "paraphrase_expansion",
        })
        idx += 1

    OUT.write_text(json.dumps(cases, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(cases)} cases to {OUT}")


if __name__ == "__main__":
    main()
