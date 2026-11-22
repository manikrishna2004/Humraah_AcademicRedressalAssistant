"""Short-lived, revisioned FastAPI conversations."""
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import StringConstraints, ValidationError

from src.academic_intake import browser_intake
from src.chat_model import Issue, StrictModel, TurnInterpretation

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "deployment" / "chat_bridge.mjs"
SESSION_SECONDS = 20 * 60
MAX_SESSIONS = 128
MAX_TURNS = 60


class ChatTurn(StrictModel):
    session: UUID | None = None
    revision: int = 0
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=700)]
    choice: Annotated[str, StringConstraints(max_length=100)] | None = None
    topic: Issue | None = None
    rewind: int | None = None

    # JSON sends a string for the session token even during Python-mode request validation.
    model_config = {"strict": False, "extra": "forbid"}


@dataclass
class ChatSession:
    turns: list[dict] = field(default_factory=list)
    revision: int = 0
    touched: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


async def run_bridge(operation: str, intake: dict, **data) -> dict:
    process = await asyncio.create_subprocess_exec(
        "node", str(BRIDGE),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        output, _ = await asyncio.wait_for(
            process.communicate(json.dumps({"operation": operation, "intake": intake, **data}).encode()),
            timeout=10,
        )
    except (TimeoutError, asyncio.CancelledError):
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise
    if process.returncode:
        raise RuntimeError(f"Conversation {operation} failed")
    return json.loads(output)


class ChatSessions:
    def __init__(self, plan: Callable[[dict], Awaitable[dict]], departments: list[str]):
        self.sessions: dict[UUID, ChatSession] = {}
        self.plan = plan
        self.intake = {**browser_intake(), "departments": departments}

    async def turn(self, request: ChatTurn) -> dict:
        if request.rewind is not None and request.session is None:
            raise HTTPException(422, "Start a conversation before editing an answer.")
        cutoff = time.monotonic() - SESSION_SECONDS
        for key, existing in list(self.sessions.items()):
            if existing.touched < cutoff and not existing.lock.locked():
                self.sessions.pop(key, None)
        created = request.session is None
        session_id = request.session or uuid4()
        session = self.sessions.get(session_id)
        if created:
            if request.revision or request.choice:
                raise HTTPException(422, "Start with a new question.")
            if len(self.sessions) >= MAX_SESSIONS:
                raise HTTPException(503, "Humraah is busy. Please try again shortly.")
            session = self.sessions[session_id] = ChatSession()
        if session is None:
            raise HTTPException(404, "This conversation has expired. Start a new question.")
        try:
            async with session.lock:
                return await self._advance(session_id, session, request)
        except BaseException:
            if created:
                self.sessions.pop(session_id, None)
            raise

    async def _advance(self, session_id: UUID, session: ChatSession, request: ChatTurn) -> dict:
        if session.revision != request.revision:
            raise HTTPException(409, "That turn has changed. Try again from the latest reply.")
        position = len(session.turns) if request.rewind is None else request.rewind
        if not 0 <= position <= len(session.turns):
            raise HTTPException(422, "Choose a reply to edit.")
        if position >= MAX_TURNS:
            raise HTTPException(422, "Start a new question to continue.")
        if request.topic and (position or request.topic == "other"):
            raise HTTPException(422, "Use a message to switch topics.")
        previous = session.turns[position - 1] if position else None
        state = previous["state"] if previous else None
        if request.choice and not any(
            value == request.choice for value, _ in ((state or {}).get("pending_question") or {}).get("choices", [])
        ):
            raise HTTPException(422, "Choose one of the offered answers.")
        event = request.model_dump(include={"text", "choice", "topic"})
        interpreted = await run_bridge(
            "interpret", self.intake, state=state, event=event, schema=TurnInterpretation.model_json_schema(),
        )
        validation = {"departments": self.intake["departments"]}
        TurnInterpretation.model_validate(interpreted["rules"], context=validation)
        try:
            candidate = TurnInterpretation.model_validate(interpreted["candidate"], context=validation).model_dump()
        except ValidationError:
            candidate = None
        change = await run_bridge("transition", self.intake, state=state, event=event, candidate=candidate)
        plan = related = None
        if not change["state"]["pending_question"]:
            if change["state"]["needs_replan"] or not previous or previous["plan"] is None:
                plan = await self.plan(change["main"])
                related = await self.plan(change["related"]) if change["related"] and plan["supported"] else None
            else:
                plan, related = previous["plan"], previous["related"]
        result = await run_bridge(
            "finish", self.intake, change=change, plan=plan, relatedPlan=related,
        )
        session.turns[position:] = [{"state": change["state"], "plan": plan, "related": related}]
        session.revision += 1
        session.touched = time.monotonic()
        return {**result, "session": str(session_id), "revision": session.revision, "position": position}

    def discard(self, key: UUID) -> None:
        self.sessions.pop(key, None)
