"""Exercise the browser API against labeled queries outside the retrieval corpus."""
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from src.config import settings
from src.stores import campus_directory, chroma_client, rulebook_store
from web_app import app


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    root = tmp_path_factory.mktemp("web_stores")
    isolated = replace(
        settings,
        chroma_persist_dir=str(root / "chroma"),
        sqlite_directory_db=str(root / "directory.db"),
    )
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(chroma_client, "settings", isolated)
        patch.setattr(chroma_client, "_client", None)
        patch.setattr(campus_directory, "settings", isolated)
        patch.setattr(rulebook_store, "_BM25_INDEX_PATH", root / "chroma" / "bm25_rulebook.pkl")
        with TestClient(app) as browser:
            yield browser


def request_plan(client, query, mode="campus"):
    response = client.post("/api/guidance", json={"query": query, "mode": mode})
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    return response.json()


def answer_path(result):
    return f"/api/guidance/{result['session']}/answer"


def answer(client, result, value):
    response = client.post(answer_path(result), json={"turn": result["turn"], "answer": value})
    assert response.status_code == 200, response.text
    return response.json()


def test_supplementary_deadline_links_to_campus_sources_and_surfaces_conflict(client):
    result = request_plan(client, "My supple application closed. Who handles a late request?")
    assert result["kind"] == "plan"
    assert result["issue"] == "Supplementary exam"
    assert "whether late registration is available" in result["next_step"]
    assert result["contacts"][0]["email"] == "arug@adm.iitkgp.ac.in"
    assert all(rule["url"].startswith("https://") for rule in result["rules"])
    assert any("item 9" in notice["text"] for notice in result["notices"])
    assert result["tips"] and all("Fictional example" in tip["label"] for tip in result["tips"])


@pytest.mark.parametrize(
    ("choice", "title", "reference"),
    [
        ("mid_sem_review", "Mid-sem answer script", "§30.1.3"),
        ("end_sem_appeal", "End-sem grade concern", "§30.2"),
    ],
)
def test_grade_follow_up_returns_only_the_chosen_procedure(client, choice, title, reference):
    follow_up = request_plan(client, "Where do I request a marks review as a comp sci student?")
    assert follow_up["kind"] == "clarification"
    assert {item["value"] for item in follow_up["choices"]} == {"mid_sem_review", "end_sem_appeal"}
    result = answer(client, follow_up, choice)
    assert result["issue"] == title
    assert len(result["rules"]) == 1
    assert reference in result["rules"][0]["label"]


def test_attendance_returns_real_department_and_fictional_fundae(client):
    response = client.post("/api/plan", json={
        "query": "Attendance was marked absent.",
        "tag": "attendance_waiver",
        "department": "Computer Science and Engineering",
    })
    assert response.status_code == 200
    result = response.json()
    assert result["contacts"][1]["email"] == "cseoffi@cse.iitkgp.ac.in"
    assert result["contacts"][1]["phone"] == "+91 3222 282255"
    assert result["tips"][0]["label"] == "Fictional example for the prototype"
    assert client.post("/api/plan", json={
        "query": "Attendance was marked absent.",
        "tag": "attendance_waiver",
        "mode": "sample",
    }).status_code == 422


def test_directory_matches_abbreviation_and_distinguishes_published_hours(client):
    response = client.get("/api/directory", params={"q": "ME"})
    assert response.status_code == 200
    assert [row["id"] for row in response.json()["contacts"]] == ["me"]
    found = client.get("/api/directory", params={"q": "SETU"}).json()["contacts"]
    assert found[0]["office"] == "Opposite Technology Students’ Gymkhana"
    assert found[0]["office_hours"] == "Mon–Fri, 10 am–1 pm and 4–8 pm IST"
    assert client.get("/api/directory", params={"q": "does not exist"}).json()["contacts"] == []


@pytest.mark.parametrize(("tried_email", "expected_role"), [("yes", "Mechanical Engineering office"), ("no", "Your assigned faculty advisor")])
def test_campus_advisor_follow_up_uses_the_correct_branch(client, tried_email, expected_role):
    follow_up = request_plan(client, "My adviser never got back to me. ME, BTech.")
    assert {item["value"] for item in follow_up["choices"]} == {"yes", "no"}
    result = answer(client, follow_up, tried_email)
    assert result["contacts"][0]["role"] == expected_role
    assert "48" not in result["next_step"]
    assert result["tips"] and all("Fictional example" in tip["label"] for tip in result["tips"])
    assert all(rule["url"] for rule in result["rules"])


def test_duplicate_turn_cannot_advance_the_next_checkpoint(client):
    initial = request_plan(client, "My advisor hasn't answered my message.")
    follow_up = answer(
        client, initial,
        {"department": "Civil Engineering", "degree_program": "UG 4-Year B.Tech"},
    )
    assert follow_up["session"] == initial["session"]
    assert follow_up["turn"] == 2
    duplicate = client.post(answer_path(initial), json={"turn": 1, "answer": "yes"})
    assert duplicate.status_code == 409
    assert answer(client, follow_up, "yes")["kind"] == "plan"
    assert client.post(answer_path(follow_up), json={"turn": 2, "answer": "yes"}).status_code == 404


def test_unsupported_issue_produces_no_academic_plan(client):
    result = request_plan(client, "Can you get my hostel room swapped?")
    assert result["supported"] is False
    assert result["rules"] == result["tips"] == result["contacts"] == []


def test_browser_entry_point_serves_required_assets(client):
    assert "Find your" in client.get("/").text
    assert client.get("/style.css").status_code == 200
    assert client.get("/app.js").status_code == 200
    assert len(client.get("/api/options").json()["scenarios"]) == 4


def test_resolved_browser_plan_uses_graph_sources_without_reasking(client):
    response = client.post("/api/plan", json={
        "query": "My marks look wrong.",
        "mode": "campus",
        "tag": "mid_sem_review",
    })
    assert response.status_code == 200
    result = response.json()
    assert result["issue"] == "Mid-sem answer script"
    assert "§30.1.3" in result["rules"][0]["label"]


def test_resolved_browser_plan_uses_conditional_advisor_guidance_if_unsure(client):
    response = client.post("/api/plan", json={
        "query": "My FA hasn't answered.",
        "mode": "campus",
        "tag": "escalation",
        "sent": None,
    })
    assert response.status_code == 200
    assert "If you haven't emailed" in response.json()["next_step"]
