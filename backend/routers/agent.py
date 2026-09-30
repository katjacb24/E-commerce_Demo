from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from agents import run_admin_agent, run_cluster_checks


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["agent"])


class AgentChatRequest(BaseModel):
    query: str


class AgentToolCall(BaseModel):
    """One Couchbase MCP tool invocation, with the arguments and the result."""

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    name: str
    args: dict[str, Any]
    result: str
    # "success" or "error" once the tool replied; "pending" if it never did.
    status: str
    # Written by the check run's reporting pass, and only there: a chat reply's
    # trace carries none of these, which is what marks a call as having no
    # finding against it.
    severity: str | None = None
    finding: str | None = None
    recommendation: str | None = None


class AgentChatResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    answer: str
    tool_calls: list[AgentToolCall] = Field(alias="toolCalls")


@router.post("/chat", response_model=AgentChatResponse)
async def chat(request: AgentChatRequest) -> AgentChatResponse:
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=422, detail="query must not be blank")

    try:
        run = await run_admin_agent(query)
    except Exception as exc:
        # The LangGraph run spans an LLM call and an MCP subprocess round-trip;
        # letting either failure escape uncaught would surface as a raw 500.
        logger.exception("Agent invocation failed for query=%r", query)
        raise HTTPException(status_code=502, detail=f"Agent failed: {exc}") from exc

    return AgentChatResponse(
        answer=run["answer"],
        tool_calls=[AgentToolCall.model_validate(call) for call in run["tool_calls"]],
    )


class CheckSeverityCounts(BaseModel):
    """How many tool calls the reporting pass put at each severity."""

    critical: int
    serious: int
    warning: int


class ClusterChecksResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    answer: str
    summary: str
    tool_calls: list[AgentToolCall] = Field(alias="toolCalls")
    counts: CheckSeverityCounts


@router.post("/checks", response_model=ClusterChecksResponse)
async def checks() -> ClusterChecksResponse:
    """Runs the Operations Dashboard's cluster checks.

    Separate from /chat because the run is two passes, not one, and returns the
    findings attached to the tool calls that produced them.
    """
    try:
        run = await run_cluster_checks()
    except Exception as exc:
        # Same failure surface as /chat: an LLM call plus an MCP subprocess
        # round trip, either of which would otherwise surface as a raw 500.
        logger.exception("Cluster check run failed")
        raise HTTPException(status_code=502, detail=f"Agent failed: {exc}") from exc

    return ClusterChecksResponse(
        answer=run["answer"],
        summary=run["summary"],
        tool_calls=[AgentToolCall.model_validate(call) for call in run["tool_calls"]],
        counts=CheckSeverityCounts.model_validate(run["counts"]),
    )
