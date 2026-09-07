"""
Interactive CLI for the Campus Redressal Assistant.

Each new question starts a fresh thread_id (a clean RedressalState) --
that's the natural session boundary for this assistant, since a single
query's clarification checkpoints all continue within one thread, but a
brand-new question shouldn't inherit leftover state (like a previous
query's "already sent a formal email?" answer) from an unrelated earlier
question. Within one query's flow, though, every clarification answer is
injected via Command(resume=...) into the SAME thread, which is what lets
LangGraph resume mid-graph instead of restarting.

Usage:
    python app.py
"""
from __future__ import annotations

import asyncio
import uuid

from langgraph.types import Command

from src.graph import build_graph
from src.llm import DEGREE_PROGRAMS, DEPARTMENTS

_DIVIDER = "-" * 72


def _ask_choice(prompt: str, options: list[str]) -> str:
    print(prompt)
    for i, opt in enumerate(options, 1):
        print(f"  {i}. {opt}")
    while True:
        raw = input("> ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        # also accept free-text that matches an option directly
        for opt in options:
            if raw.lower() == opt.lower():
                return opt
        print(f"Please enter a number from 1-{len(options)}.")


def _ask_yes_no(prompt: str) -> str:
    print(prompt)
    while True:
        raw = input("> (yes/no) ").strip().lower()
        if raw in {"y", "yes"}:
            return "yes"
        if raw in {"n", "no"}:
            return "no"
        print("Please answer yes or no.")


def _handle_interrupt(payload: dict) -> object:
    """Renders one clarification checkpoint as a CLI prompt and returns the
    value to resume the graph with."""
    checkpoint = payload["checkpoint"]
    print(f"\n[{checkpoint}] {payload['question']}")

    if checkpoint == "clarification_1":
        missing = payload["missing_fields"]
        answer: dict[str, str] = {}
        if "department" in missing:
            answer["department"] = _ask_choice("Department:", DEPARTMENTS)
        if "degree_program" in missing:
            answer["degree_program"] = _ask_choice("Degree program:", DEGREE_PROGRAMS)
        return answer

    if checkpoint == "clarification_2":
        return _ask_choice("Pick the matching procedure:", payload["options"])

    if checkpoint == "clarification_3":
        return _ask_yes_no("")

    raise ValueError(f"Unknown checkpoint: {checkpoint}")


async def run_one_query(graph, query: str) -> None:
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    result = await graph.ainvoke({"user_query": query}, config=config)

    while "__interrupt__" in result:
        interrupt_obj = result["__interrupt__"][0]
        answer = _handle_interrupt(interrupt_obj.value)
        result = await graph.ainvoke(Command(resume=answer), config=config)

    print(f"\n{_DIVIDER}")
    print(result.get("final_response", "(no response generated)"))
    print(f"{_DIVIDER}\n")


async def main() -> None:
    print("Campus Grievance-Redressal Assistant (LangGraph demo)")
    print("Type a question, or 'quit' to exit.\n")

    graph = build_graph()

    while True:
        query = input("You: ").strip()
        if query.lower() in {"quit", "exit"}:
            break
        if not query:
            continue
        await run_one_query(graph, query)


if __name__ == "__main__":
    asyncio.run(main())
