from __future__ import annotations

import logging
from datetime import date, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agents import run_user_agent


logger = logging.getLogger(__name__)

# The shopper-facing assistant. Kept apart from /api/agent (the admin agent),
# which runs a different prompt, a different tool set, and returns its MCP trace.
router = APIRouter(prefix="/api/assistant", tags=["assistant"])


class AssistantChatRequest(BaseModel):
    query: str
    # The signed-in shopper, and the Agent Memory session the conversation has
    # been using. Both absent means a signed-out shopper, whose chat stays
    # stateless; a user with no session yet is a conversation's first turn.
    user_id: str | None = None
    username: str | None = None
    session_id: str | None = None
    # How many turns this conversation has already had, echoed back from the
    # previous response. It selects the shape of recall — verbatim window
    # versus semantic search — so it rides with the request rather than costing
    # a round trip to the memory server to count blocks on every turn.
    turn_count: int = 0

    # --- Presenter controls, for driving the demo ---------------------------
    # The date this session should appear to have happened on ("YYYY-MM-DD").
    # Memories written this turn are attributed to it; the time of day comes
    # from the real clock so turns within the session stay in order.
    session_date: str | None = None
    # How long this session's message memories should survive, in seconds, with
    # 0 meaning never expire. Only the request that opens the session can set
    # it, because retention is fixed when the session is created.
    session_retention_seconds: int | None = None


class AssistantChatResponse(BaseModel):
    answer: str
    # Returned so the panel can send it back on the next turn and keep the whole
    # conversation inside one session.
    session_id: str | None = None
    # This turn included, so the panel can send it straight back.
    turn_count: int = 0
    # The retention this session was actually opened with, so the panel can show
    # what is in force rather than what was typed. None when memory is off.
    session_retention_seconds: int | None = None


def _resolve_created_at(session_date: str | None) -> str | None:
    """Turn a presenter's chosen date into the timestamp memories are filed under.

    The date decides the day; the time of day comes from the real clock, so
    successive turns of a dated session stay in chronological order relative to
    one another instead of all sharing one instant.

    A malformed date is rejected rather than quietly ignored: silently recording
    a dated conversation at today's date would look like the control is broken.
    """
    raw = (session_date or "").strip()
    if not raw:
        return None

    try:
        chosen = date.fromisoformat(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="session_date must be a date in YYYY-MM-DD form.",
        ) from exc

    now = datetime.now()
    return datetime.combine(chosen, now.time()).isoformat()


def _resolve_retention(retention_seconds: int | None) -> int | None:
    """Validate the retention a presenter asked this session to be opened with.

    None means "use the configured default". 0 means never expire, which is why
    it cannot be conflated with None.
    """
    if retention_seconds is None:
        return None
    if retention_seconds < 0:
        raise HTTPException(
            status_code=422,
            detail="session_retention_seconds must be 0 or greater (0 means never expire).",
        )
    return retention_seconds


@router.post("/chat", response_model=AssistantChatResponse)
async def chat(request: AssistantChatRequest) -> AssistantChatResponse:
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=422, detail="query must not be blank")

    # Blank strings reach here from a form as readily as nulls do, and both mean
    # "not signed in" rather than a shopper whose id is "".
    user_id = (request.user_id or "").strip() or None
    username = (request.username or "").strip() or None
    session_id = (request.session_id or "").strip() or None

    # A negative count would be read as "no turns yet" anyway; clamping keeps the
    # recall thresholds working on a number that makes sense.
    turn_count = max(request.turn_count, 0)
    created_at = _resolve_created_at(request.session_date)
    retention = _resolve_retention(request.session_retention_seconds)

    try:
        run = await run_user_agent(
            query,
            user_id=user_id,
            username=username,
            session_id=session_id,
            turn_count=turn_count,
            created_at=created_at,
            retention_seconds=retention,
        )
    except Exception as exc:
        # The run spans an LLM call and an MCP subprocess round-trip; letting
        # either failure escape uncaught would surface as a raw 500.
        logger.exception("User agent invocation failed for query=%r", query)
        raise HTTPException(
            status_code=502, detail="The assistant could not process your request."
        ) from exc

    return AssistantChatResponse(
        answer=run["answer"],
        session_id=run["session_id"],
        turn_count=turn_count + 1,
        session_retention_seconds=run["retention_seconds"],
    )
