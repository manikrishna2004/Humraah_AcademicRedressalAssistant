"""
End-to-end smoke tests for the LangGraph pipeline, run entirely in mock
mode (no Ollama / no downloaded embedding model / no network access).

Run with:  pytest -q
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
from langgraph.types import Command

from src.graph import build_graph
from src.stores import directory_store, rulebook_store, senior_experience_store

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture(scope="session", autouse=True)
def _ingested_stores():
    """
    Ingest the sample data (data/*.csv, data/*.json) into the project's own
    ./data store before the test session, exactly as `python
    scripts/ingest_data.py` does. Mock embeddings + a small fixed dataset
    make this fast and fully offline, so re-ingesting per test run is cheap
    and keeps tests self-contained (no separate setup step required).
    """
    directory_store.load_csv(DATA_DIR / "faculty_directory.csv", DATA_DIR / "student_reps.csv")
    senior_experience_store.load_json(DATA_DIR / "senior_experiences.json")
    rulebook_store.load_json(DATA_DIR / "rulebook_chunks.json")
    yield


def _new_config() -> dict:
    return {"configurable": {"thread_id": str(uuid.uuid4())}}


def test_clean_single_path_reaches_synthesizer():
    graph = build_graph()

    async def run():
        return await graph.ainvoke(
            {"user_query": "Room reallocation process for hostel, Mechanical Engineering"},
            config=_new_config(),
        )

    result = asyncio.run(run())
    assert "__interrupt__" not in result
    assert result["gate_decision"] == "synthesize"
    assert "Chief Warden" in result["final_response"]


def test_clarification_1_missing_entity_then_resume():
    graph = build_graph()
    config = _new_config()

    async def run():
        r1 = await graph.ainvoke(
            {"user_query": "My advisor is ignoring my attendance waiver request."},
            config=config,
        )
        assert "__interrupt__" in r1
        assert r1["__interrupt__"][0].value["checkpoint"] == "clarification_1"

        r2 = await graph.ainvoke(
            Command(resume={"department": "Civil Engineering", "degree_program": "UG 4-Year B.Tech"}),
            config=config,
        )
        return r2

    result = asyncio.run(run())
    assert "__interrupt__" not in result
    # Node 1 must not have been re-run: category/subcategory survive untouched
    assert result["category"] == "Academic"
    assert result["department"] == "Civil Engineering"
    assert result["final_response"]


def test_clarification_2_ambiguity_filters_context():
    graph = build_graph()
    config = _new_config()

    async def run():
        r1 = await graph.ainvoke(
            {"user_query": "How do I apply for a grade review in Computer Science and Engineering?"},
            config=config,
        )
        assert r1["__interrupt__"][0].value["checkpoint"] == "clarification_2"
        options = r1["__interrupt__"][0].value["options"]
        assert "mid_sem_review" in options and "end_sem_appeal" in options

        r2 = await graph.ainvoke(Command(resume="mid_sem_review"), config=config)
        return r2

    result = asyncio.run(run())
    assert result["ambiguity_resolved"] == "mid_sem_review"
    for hit in result["retrieved_senior_fundae"] + result["retrieved_rules"]:
        assert hit["tag"] == "mid_sem_review"


def test_clarification_3_escalation_action_plan():
    graph = build_graph()
    config = _new_config()

    async def run():
        r1 = await graph.ainvoke(
            {
                "user_query": (
                    "My FA is unresponsive, should I go to the HOD? "
                    "Mechanical Engineering, UG 4-year"
                )
            },
            config=config,
        )
        assert r1["__interrupt__"][0].value["checkpoint"] == "clarification_3"
        r2 = await graph.ainvoke(Command(resume="yes"), config=config)
        return r2

    result = asyncio.run(run())
    assert result["formal_email_sent"] is True
    assert "escalation" in result["final_response"].lower() or "HOD" in result["final_response"]


def test_out_of_domain_gates_to_web_search():
    graph = build_graph()

    async def run():
        return await graph.ainvoke(
            {"user_query": "What is the weather like today?"}, config=_new_config()
        )

    result = asyncio.run(run())
    assert result["route_decision"] == "web_search"
    assert result["web_search_results"]
    # Node 2 still runs regardless -- local stores are always given a chance
    assert "retrieved_directory" in result
