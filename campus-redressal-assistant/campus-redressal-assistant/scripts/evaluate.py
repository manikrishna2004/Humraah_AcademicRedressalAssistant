"""
Evaluation harness for the Campus Redressal Assistant pipeline.

Runs every labeled case in eval/test_queries.json through the compiled
LangGraph, feeding scripted clarification answers via Command(resume=...),
and scores four things:

  1. Intent accuracy      -- did Node 1 extract the right department/subcategory?
  2. Routing accuracy     -- did it take the right route out of Node 1
                             (retrieve / clarify_1 / web_search) and the right
                             gate_decision (synthesize / clarify_2 / clarify_3)?
  3. Retrieval accuracy   -- does the single highest-scoring retrieved chunk
                             carry the expected subcategory tag?
  4. Escalation precision/recall -- of queries labeled `is_escalation`, how
                             many correctly triggered Clarification Point 3;
                             of queries NOT labeled escalation, how many
                             falsely did?

Also runs a structural groundedness check: every chunk the synthesizer
decided was strong enough to show (see src/nodes/synthesizer.py's
_MIN_ITEM_SCORE filter) must appear verbatim in the final answer. In mock
mode this is closer to a regression guard than a real signal, since the
mock renderer only ever echoes retrieved text -- it becomes a meaningful
check once LLM_BACKEND=ollama and the model is free to paraphrase or drift.

"Action-plan relevance" is NOT auto-scored here -- whether the actual
steps are the *right* steps is a judgment call, not a string comparison.
This script emits a `human_rating` column (1-5, left blank) in
eval/results.csv for a human (or an LLM-as-judge call you wire in
yourself) to fill in against a rubric -- see the bottom of this file.

Usage:
    python scripts/evaluate.py
    python scripts/evaluate.py --cases eval/test_queries.json --out eval/
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langgraph.types import Command  # noqa: E402

from src.graph import build_graph  # noqa: E402
from src.nodes.synthesizer import _MIN_ITEM_SCORE  # noqa: E402


def _top_tag(state: dict) -> str | None:
    hits = (state.get("retrieved_senior_fundae") or []) + (state.get("retrieved_rules") or [])
    if not hits:
        return None
    return max(hits, key=lambda h: h.get("score", 0)).get("tag") or None


def _check_groundedness(state: dict) -> bool:
    final_response = state.get("final_response") or ""
    for key in ("retrieved_senior_fundae", "retrieved_rules"):
        shown = sorted(
            (h for h in state.get(key) or [] if h.get("score", 0) >= _MIN_ITEM_SCORE),
            key=lambda h: h.get("score", 0),
            reverse=True,
        )[:3]
        for hit in shown:
            if hit["text"] not in final_response:
                return False
    return True


async def _run_case(graph, case: dict) -> dict:
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    resumes = list(case["resume_answers"])

    state = await graph.ainvoke({"user_query": case["query"]}, config=config)
    while "__interrupt__" in state:
        if not resumes:
            # Not a script bug -- the pipeline hit a checkpoint the test case
            # didn't anticipate. Record it as a failure on every metric
            # rather than crashing, since "asked an unexpected clarifying
            # question" is itself a real routing failure worth counting.
            expected = case["expected"]
            return {
                "id": case["id"],
                "query": case["query"],
                "note": case.get("note", "") + " [UNEXPECTED INTERRUPT]",
                "intent_correct": False,
                "route_correct": False,
                "gate_correct": False,
                "retrieval_correct": False,
                "groundedness_ok": False,
                "is_escalation": expected["is_escalation"],
                "predicted_escalation_trigger": state["__interrupt__"][0].value.get("checkpoint")
                == "clarification_3",
                "actual_department": state.get("department"),
                "actual_subcategory": state.get("subcategory"),
                "actual_route": state.get("route_decision"),
                "actual_gate": state["__interrupt__"][0].value.get("checkpoint"),
                "actual_top_tag": _top_tag(state),
            }
        state = await graph.ainvoke(Command(resume=resumes.pop(0)), config=config)

    expected = case["expected"]
    predicted_escalation_trigger = state.get("gate_decision") == "clarify_3"

    return {
        "id": case["id"],
        "query": case["query"],
        "note": case.get("note", ""),
        "intent_correct": (
            state.get("department") == expected["department"]
            and state.get("subcategory") == expected["subcategory"]
        ),
        "route_correct": state.get("route_decision") == expected["route_decision"],
        "gate_correct": state.get("gate_decision") == expected["gate_decision"],
        "retrieval_correct": (
            expected["top_tag"] is None or _top_tag(state) == expected["top_tag"]
        ),
        "groundedness_ok": _check_groundedness(state),
        "is_escalation": expected["is_escalation"],
        "predicted_escalation_trigger": predicted_escalation_trigger,
        "actual_department": state.get("department"),
        "actual_subcategory": state.get("subcategory"),
        "actual_route": state.get("route_decision"),
        "actual_gate": state.get("gate_decision"),
        "actual_top_tag": _top_tag(state),
    }


def _print_report(results: list[dict]) -> None:
    n = len(results)
    print(f"\n=== Evaluation report: {n} test queries ===\n")

    metrics = ["intent_correct", "route_correct", "gate_correct", "retrieval_correct", "groundedness_ok"]
    for metric in metrics:
        passed = sum(1 for r in results if r.get(metric) is True)
        print(f"{metric:22s}: {passed}/{n} ({passed / n:.0%})")

    escalation_cases = [r for r in results if r["is_escalation"]]
    non_escalation_cases = [r for r in results if not r["is_escalation"]]
    tp = sum(1 for r in escalation_cases if r["predicted_escalation_trigger"])
    fn = len(escalation_cases) - tp
    fp = sum(1 for r in non_escalation_cases if r["predicted_escalation_trigger"])
    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    print(f"\nEscalation precision: {precision:.0%}  (TP={tp}, FP={fp})")
    print(f"Escalation recall:    {recall:.0%}  (TP={tp}, FN={fn})")

    failures = [r for r in results if not all(r.get(m) for m in metrics)]
    print(f"\n{len(failures)} case(s) with at least one failing metric:")
    for r in failures:
        failed = [m for m in metrics if not r.get(m)]
        print(f"  - {r['id']}: failed {failed}")
        print(f"      query: {r['query']}")
        print(
            f"      expected vs actual -- dept: ?/{r['actual_department']}  "
            f"subcat: ?/{r['actual_subcategory']}  route: ?/{r['actual_route']}  "
            f"gate: ?/{r['actual_gate']}  top_tag: ?/{r['actual_top_tag']}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", default="eval/test_queries.json")
    parser.add_argument("--out", default="eval")
    args = parser.parse_args()

    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    graph = build_graph()

    async def run_all():
        return [await _run_case(graph, case) for case in cases]

    results = asyncio.run(run_all())
    _print_report(results)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(out_dir / "results.csv", "w", newline="", encoding="utf-8") as f:
        fieldnames = list(results[0].keys()) + ["human_rating_action_plan_1to5"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow({**r, "human_rating_action_plan_1to5": ""})

    failures = [
        r
        for r in results
        if not all(
            r.get(m)
            for m in ("intent_correct", "route_correct", "gate_correct", "retrieval_correct", "groundedness_ok")
        )
    ]
    (out_dir / "failures.json").write_text(json.dumps(failures, indent=2), encoding="utf-8")

    print(f"\nWrote eval/results.csv ({len(results)} rows) and eval/failures.json ({len(failures)} rows).")
    print(
        "Fill in the human_rating_action_plan_1to5 column by hand (or wire in an "
        "LLM-as-judge call) against a rubric like:\n"
        "  5 - correct, complete, in the right order\n"
        "  3 - right idea but missing/soft on a required step\n"
        "  1 - wrong department/procedure, or contradicts the rulebook"
    )


if __name__ == "__main__":
    main()
