"""Evaluate six independent reviewer conversations against the real chat API."""
from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from urllib.request import Request, urlopen

ACADEMIC_UG = "arug@adm.iitkgp.ac.in"
CSE_OFFICE = "cseoffi@cse.iitkgp.ac.in"


def evaluate(send: Callable[..., dict], close: Callable[[dict], None]) -> list[dict]:
    active = []

    def talk(text: str, previous: dict | None = None) -> dict:
        state = send(text, previous)
        if previous is None:
            active.append(state)
        return state

    def row(label: str, expected: str, actual: str, turns: int, *checks: bool) -> dict:
        return dict(case=label, expected=expected, actual=actual, turns_to_action=turns, passed=all(checks))

    try:
        mixed = talk("My FA hasn't replied and the suppli form closes soon")
        plan = mixed["plan"]
        if not plan:
            raise AssertionError(f"Mixed request asked {mixed['question']}")
        primary = plan["contacts"][0]
        secondary = plan["related"]["contacts"][0]
        rows = [row(
            "Near deadline and unanswered advisor",
            "Give supplementary registration guidance and a sourced academic contact, retain the advisor issue, and flag the deadline for confirmation.",
            f"{primary['role']} ({primary['email']}), plus {secondary['role']}. {plan['notices'][0]['text']}",
            1, mixed["question"] is None, mixed["state"]["deadline"]["verified"] is False,
            primary["email"] == ACADEMIC_UG, secondary["id"] == "faculty-advisor",
            all(claim["url"] and claim["verified_at"] for claim in plan["rules"]),
        )]

        grade = talk("I'm worried about my grade")
        question = grade["question"]
        clarified = talk("I think my final grade is wrong and want to appeal it.", grade)
        rows.append(row(
            "Vague grade concern",
            "Ask one question about the grade concern, then resolve the stated final-grade appeal without re-asking.",
            f"{question['text']} → {clarified['plan']['issue']}, {clarified['plan']['rules'][0]['label']}",
            2, question["id"] == "grade", grade["plan"] is None,
            clarified["question"] is None, clarified["plan"]["issue"] == "End-sem grade concern",
            "§30.2" in clarified["plan"]["rules"][0]["label"],
        ))

        advisor = talk("I already emailed my CSE faculty advisor and haven't heard back.")
        cse = advisor["plan"]["contacts"][0]
        corrected = talk("Actually, I'm in EE", advisor)
        ee = corrected["plan"]["contacts"][0]
        still_ee = talk("Who should I contact?", corrected)
        rows.append(row(
            "Department correction after a plan",
            "Replace CSE with the Electrical Engineering record, retain the advisor issue, and use the corrected contact on the next turn.",
            f"{cse['role']} → {ee['role']} ({ee['email'] or ee['phone']}). {still_ee['response']['text']}",
            2, cse["email"] == CSE_OFFICE, ee["id"] == "ee",
            corrected["question"] is None, corrected["state"]["department"]["source"] == "stated",
            corrected["state"]["needs_replan"], (ee["email"] or ee["phone"]) in still_ee["response"]["text"],
        ))

        initial = talk("My faculty advisor in CSE isn't responding.")
        escalated = talk("Emailed my advisor 5 days ago, nothing", initial)
        draft = escalated["response"]
        rows.append(row(
            "Advisor email received no reply",
            "Remember the email, give a follow-up draft and the official department escalation contact.",
            f"{draft['text']} {draft['draft'].splitlines()[0]}",
            2, initial["question"]["id"] == "sent", escalated["question"] is None,
            bool(draft["draft"]), CSE_OFFICE in [item["label"] for item in draft["links"]],
            "directory:cse" in draft["claim_ids"], escalated["state"]["actions_taken"][0]["value"],
        ))

        conflict = talk("Does a supplementary registration require a head of department signature?")
        notice = next(n for n in conflict["plan"]["notices"] if n["title"] == "Sources give different instructions")
        refs = notice["links"]
        rows.append(row(
            "Conflicting supplementary signature instructions",
            "Show the conflicting instructions, cite official references, and identify the office to confirm.",
            f"{notice['text']} {len(refs)} linked references.",
            1, "item 9" in notice["text"], "item 17" in notice["text"],
            any("FACULTYADVISOR" in link["url"] for link in refs),
            any("comdir.pdf" in link["url"] for link in refs), conflict["plan"]["contacts"][0]["email"] == ACADEMIC_UG,
        ))

        request = talk("I am looking for help with supplementary exam registration.")
        visit = talk("Where do I go and when?", request)
        office = visit["response"]
        rows.append(row(
            "Office visit with no published hours",
            "Give the verified office, contact channel and what to ask before visiting when hours are missing.",
            office["text"],
            2, "Institute Main Building" in office["text"], "doesn’t publish visiting hours" in office["text"],
            "counter" in office["text"] and "floor" in office["text"],
            any(item["url"].startswith("tel:") for item in office["links"]),
            "directory:acad-ug" in office["claim_ids"],
        ))
        return rows
    finally:
        for session in active:
            close(session)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Root URL for FastAPI, a local Worker, or the public site")
    args = parser.parse_args()
    base = args.url.rstrip("/")

    def send(text: str, previous: dict | None) -> dict:
        payload = {"text": text, **({key: previous[key] for key in ("session", "revision")} if previous else {})}
        request = Request(
            f"{base}/api/chat/turn", method="POST", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=20) as response:
            return json.load(response)

    def close(session: dict) -> None:
        with urlopen(Request(f"{base}/api/chat/{session['session']}", method="DELETE"), timeout=10):
            pass

    results = evaluate(send, close)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    if not all(result["passed"] for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
