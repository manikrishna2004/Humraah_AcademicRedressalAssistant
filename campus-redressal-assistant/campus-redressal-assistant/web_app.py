"""Browser entry point for Humraah. Run via scripts/run_web.py."""
from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, StringConstraints

from src.academic_intake import ISSUES, browser_intake
from src.graph import build_graph
from src.llm import DEGREE_PROGRAMS, DEPARTMENTS
from src.stores import directory_store, rulebook_store, senior_experience_store

ROOT = Path(__file__).resolve().parent
MAX_PENDING = 128
SESSION_SECONDS = 20 * 60

FIELD_OPTIONS = {"department": DEPARTMENTS, "degree_program": DEGREE_PROGRAMS}
FIELD_LABELS = {"department": "Department", "degree_program": "Degree program"}
MODE = Literal["campus", "sample"]


class StartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=700)]
    mode: MODE = "campus"


class PlanRequest(StartRequest):
    tag: Literal["supplementary_exam", "mid_sem_review", "end_sem_appeal", "attendance_waiver", "escalation"] | None
    department: str | None = None
    degree_program: str | None = None
    sent: bool | None = None


class ResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    turn: int
    answer: str | dict[str, str]


@dataclass
class Pending:
    turn: int = 0
    question: dict | None = None
    touched: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@asynccontextmanager
async def lifespan(app: FastAPI):
    data = ROOT / "data"
    directory_store.load_csv(data / "faculty_directory.csv", data / "student_reps.csv")
    senior_experience_store.load_json(data / "senior_experiences.json")
    rulebook_store.load_json(data / "rulebook_chunks.json", data / "campus_sources.json")
    app.state.checkpointer = MemorySaver()
    app.state.graph = build_graph(app.state.checkpointer)
    app.state.pending = {}
    yield


app = FastAPI(title="Humraah", lifespan=lifespan, openapi_url=None)


@app.middleware("http")
async def prevent_session_caching(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/options")
def options():
    return browser_intake()


async def forget(thread_id: str) -> None:
    app.state.pending.pop(thread_id, None)
    await app.state.checkpointer.adelete_thread(thread_id)


async def advance(thread_id: str, pending: Pending, graph_input: dict | Command) -> dict:
    config = {"configurable": {"thread_id": thread_id}}
    try:
        result = await app.state.graph.ainvoke(graph_input, config=config)
    except Exception:
        await forget(thread_id)
        raise

    if interrupts := result.get("__interrupt__"):
        pending.turn += 1
        pending.touched = time.monotonic()
        question = interrupts[0].value
        pending.question = question
        fields = [
            {"key": key, "label": FIELD_LABELS[key], "options": FIELD_OPTIONS[key]}
            for key in question.get("missing_fields", [])
        ]
        choices = [
            {"value": value, "label": ISSUES.get(value, value.capitalize())}
            for value in question.get("options", [])
        ]
        return {
            "kind": "clarification",
            "session": thread_id,
            "turn": pending.turn,
            "question": question["question"],
            "fields": fields,
            "choices": choices,
        }

    await forget(thread_id)
    return {"kind": "plan", **result["action_plan"]}


@app.post("/api/plan")
async def plan(request: PlanRequest):
    if request.department is not None and request.department not in DEPARTMENTS:
        raise HTTPException(422, "Choose a department from the list.")
    if request.degree_program is not None and request.degree_program not in DEGREE_PROGRAMS:
        raise HTTPException(422, "Choose a degree program from the list.")
    thread_id = str(uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    try:
        result = await app.state.graph.ainvoke({
            "user_query": request.query,
            "academic_mode": request.mode,
            "guided_resolution": True,
            "subcategory": request.tag,
            "department": request.department,
            "degree_program": request.degree_program,
            "formal_email_sent": request.sent,
        }, config=config)
        return result["action_plan"]
    finally:
        await forget(thread_id)


@app.post("/api/guidance")
async def start(request: StartRequest):
    pending_sessions = app.state.pending
    cutoff = time.monotonic() - SESSION_SECONDS
    for thread_id, pending in list(pending_sessions.items()):
        if pending.touched < cutoff and not pending.lock.locked():
            await forget(thread_id)
    if len(pending_sessions) >= MAX_PENDING:
        raise HTTPException(503, "Humraah is busy. Please try again shortly.")

    thread_id = str(uuid4())
    pending = pending_sessions[thread_id] = Pending()
    async with pending.lock:
        return await advance(
            thread_id,
            pending,
            {"user_query": request.query, "academic_mode": request.mode},
        )


@app.post("/api/guidance/{session}/answer")
async def resume(session: UUID, request: ResumeRequest):
    thread_id = str(session)
    pending = app.state.pending.get(thread_id)
    if pending is None:
        raise HTTPException(404, "This question has expired. Please start a new one.")

    async with pending.lock:
        if app.state.pending.get(thread_id) is not pending:
            raise HTTPException(404, "This question has expired. Please start a new one.")
        if time.monotonic() - pending.touched > SESSION_SECONDS:
            await forget(thread_id)
            raise HTTPException(404, "This question has expired. Please start a new one.")
        question = pending.question
        if not question or request.turn != pending.turn:
            raise HTTPException(409, "This follow-up has already been answered.")

        missing = question.get("missing_fields", [])
        answer = request.answer
        if missing:
            valid = isinstance(answer, dict) and set(answer) == set(missing) and all(
                answer[key] in FIELD_OPTIONS[key] for key in missing
            )
        else:
            valid = isinstance(answer, str) and answer in question.get("options", [])
        if not valid:
            raise HTTPException(422, "Choose one of the available answers.")
        return await advance(thread_id, pending, Command(resume=answer))


@app.delete("/api/guidance/{session}", status_code=204)
async def discard(session: UUID):
    thread_id = str(session)
    pending = app.state.pending.get(thread_id)
    if pending:
        async with pending.lock:
            await forget(thread_id)
    return Response(status_code=204)


app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
