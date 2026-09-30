import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import Any, Literal, TypedDict
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, END, START
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langchain.tools import tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

# --- Load backend/.env (one level up from this file) ---
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
if not load_dotenv(ENV_PATH):
    raise RuntimeError(f"Could not load env file at {ENV_PATH}")


# --- Configure the Couchbase MCP Server (launched as a stdio subprocess) ---
# The MCP server is a separate process. We describe how to start it; the adapter
# spawns it, speaks MCP over stdin/stdout, and turns its tools into LangChain tools.
UVX = os.getenv("UVX_PATH") or shutil.which("uvx")
if UVX is None:
    raise RuntimeError(
        "uvx not found. Install it with `pip install uv` (or `brew install uv`), "
        "or set UVX_PATH to its absolute path."
    )

MCP_SERVERS = {
    "couchbase": {
        "transport": "stdio",
        "command": UVX,
        "args": ["couchbase-mcp-server"],
        # The server reads CB_* names; .env uses COUCHBASE_* names.
        "env": {
            **os.environ,  # uvx needs PATH/HOME to resolve its cached environment
            "CB_CONNECTION_STRING": os.environ["COUCHBASE_CONNECTION_STRING"],
            "CB_USERNAME": os.environ["COUCHBASE_USERNAME"],
            "CB_PASSWORD": os.environ["COUCHBASE_PASSWORD"],
            "CB_MCP_READ_ONLY_MODE": "false",
        },
    }
}


# --- Initialize LLM ---
# If OpenAI model is used
llm = ChatOpenAI(model=os.getenv("OPEN_AI_MODEL"), temperature=0)
# If Capella-hosted LLM is used
# llm = ChatOpenAI(
#     model=os.getenv("LLM_MODEL"),
#     base_url=os.getenv("LLM_BASE_URL"),   
#     api_key=os.getenv("LLM_API_KEY"),
#     temperature=0,
# )

# --- Define Shared State ---
class ToolCallTrace(TypedDict):
    """One tool invocation the agent made, paired with what the tool returned."""
    name: str
    args: dict[str, Any]
    result: str
    status: str


class AnnotatedToolCall(ToolCallTrace, total=False):
    """A tool call with the check run's verdict on it attached.

    The three extra keys are written by the reporting pass in
    run_cluster_checks() and are absent on a call that surfaced nothing, which
    is what lets the dashboard render "No findings." for it.
    """
    severity: str
    finding: str
    recommendation: str


class AgentState(TypedDict):
    user_query: str
    answer: str
    tool_calls: list[ToolCallTrace]


def _stringify_content(content: Any) -> str:
    """Flatten a message's content into display text.

    Tool results arrive either as a plain string or as a list of content blocks
    (MCP servers commonly return the latter), so both shapes are normalised here
    rather than at each call site.
    """
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(block.get("text") or json.dumps(block, default=str))
            else:
                parts.append(str(block))
        return "\n".join(parts)
    return str(content)


def _extract_tool_calls(messages: list[Any]) -> list[ToolCallTrace]:
    """Pair every tool call in the run with the result that answered it.

    The agent loop leaves an interleaved transcript: an AIMessage carrying
    `tool_calls`, then one ToolMessage per call. ToolMessages reference the call
    they answer by id, so results are indexed by id first and the transcript is
    then walked in order to keep the calls in the sequence the agent made them.
    """
    results_by_id: dict[str, ToolMessage] = {
        message.tool_call_id: message
        for message in messages
        if isinstance(message, ToolMessage)
    }

    traces: list[ToolCallTrace] = []
    for message in messages:
        for call in getattr(message, "tool_calls", None) or []:
            result = results_by_id.get(call.get("id"))
            traces.append(
                ToolCallTrace(
                    name=call.get("name") or "",
                    args=call.get("args") or {},
                    # A call with no matching ToolMessage never returned — the run
                    # was cut short (recursion limit, error) before the tool replied.
                    result=_stringify_content(result.content) if result else "",
                    status=(getattr(result, "status", "success") or "success")
                    if result
                    else "pending",
                )
            )
    return traces

# --- Define Couchbase Agent ---
# Steps the ReAct loop may take before LangGraph stops it.
AGENT_RECURSION_LIMIT = 80

# Every tool result stays in the agent's message history for the rest of the
# run, and query-diagnostics results can be tens of kilobytes each, so a dozen
# calls overflow a 128k-token window. ~2k tokens per result keeps the whole run in budget.
MAX_TOOL_RESULT_CHARS = 8_000


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}\n… [{len(text) - max_chars} more characters omitted]"


def _cap_tool_output(tool: Any, max_chars: int = MAX_TOOL_RESULT_CHARS) -> Any:
    """Wrap an MCP tool so the text it hands back to the model is capped at max_chars."""
    call = tool.coroutine

    async def capped_call(*args, **kwargs):
        # MCP adapter tools return (content, artifact); only content reaches the model.
        content, artifact = await call(*args, **kwargs)
        if isinstance(content, str):
            content = _truncate(content, max_chars)
        elif isinstance(content, list):
            content = [
                {**block, "text": _truncate(block["text"], max_chars)}
                if isinstance(block, dict) and isinstance(block.get("text"), str)
                else block
                for block in content
            ]
        return content, artifact

    tool.coroutine = capped_call
    return tool

COUCHBASE_SYSTEM_PROMPT = f"""
    You are a Couchbase data analyst and DevOps engineer. Answer questions about the data stored in the
    cluster and about cluster health and performance by calling the available Couchbase tools - never guess at data.

    Default target for this application:
    bucket:     {os.getenv("COUCHBASE_BUCKET")}
    scope:      {os.getenv("COUCHBASE_SCOPE")}
    collection: {os.getenv("COUCHBASE_COLLECTION")}
    FTS index:  {os.getenv("COUCHBASE_FTS_INDEX")}

    When calling test_cluster_connection, always pass bucket_name={os.getenv("COUCHBASE_BUCKET")}.

    Inspect the collection schema before writing a query. 
    If the question includes the description of the product, e.g. "Find 5 products with floral print", use the FTS SEARCH function within the SQL++ query like this: 
    "SELECT p.meta().id, p.description FROM `webshop`.`webshop-scope`.`products` AS p WHERE SEARCH(p.description, "floral print") ORDER BY SEARCH_SCORE() DESC
    LIMIT 5; "
    Always return relevant fields including the document ID within the SELECT statement of SQL++ (example: "SELECT meta().id, name, price.amount, price.currency FROM `webshop`.`webshop-scope`.`products` WHERE category.subtype = 'Blouses' AND price.amount < 30 AND price.currency = 'EUR' LIMIT 1;"). 
    Always use the fully qualified keyspace `bucket`.`scope`.`collection` in SQL++ queries. 
    Answer in plain English.
"""

async def couchbase_agent(state: AgentState) -> dict:
    """
    Answers questions about data stored in the Couchbase cluster: products,
    cluster health, collections, schemas, SQL++ queries, indexes and query performance.

    Runs a ReAct-style agent whose tools are supplied at runtime by the Couchbase
    MCP Server (schema discovery, document lookup by ID, SQL++ execution, index
    advice, slow-query analysis).

    Args:
        state (AgentState): A dictionary with the user's query.

    Returns:
        dict: Updated state with the generated answer and the tool calls that
            produced it.
    """
    print("--- Couchbase Node ---")
    client = MultiServerMCPClient(MCP_SERVERS)
    # One session for the whole agent run: the server process starts here and is
    # torn down on exit, so every tool call in the loop reuses one connection.
    async with client.session("couchbase") as session:
        tools = [_cap_tool_output(t) for t in await load_mcp_tools(session)]
        print(f"Loaded {len(tools)} MCP tools: {[t.name for t in tools][:5]} ...")
        agent = create_agent(llm, tools, system_prompt=COUCHBASE_SYSTEM_PROMPT)
        result = await agent.ainvoke(
            {"messages": state["user_query"]},
            # A check run is a long loop — eight baseline checks, then follow-up
            # tools for each finding — and LangGraph's default of 25 steps cuts
            # it off mid-way, which surfaces as `pending` calls in the trace.
            config={"recursion_limit": AGENT_RECURSION_LIMIT},
        )
    print(result["messages"][-1].content)
    return {
        "answer": _stringify_content(result["messages"][-1].content),
        "tool_calls": _extract_tool_calls(result["messages"]),
    }


# --- Build the Graph ---
# couchbase_agent is the only node, so there is nothing to route between.
workflow = StateGraph(AgentState)
workflow.add_node("couchbase_agent", couchbase_agent) # Adds the MCP-backed agent
workflow.add_edge(START, "couchbase_agent")
workflow.add_edge("couchbase_agent", END)

app = workflow.compile()


async def run_agent(user_query: str) -> AgentState:
    """
    Runs the compiled graph for a single query and returns its final state.

    This is the entry point the FastAPI layer calls; MCP tools are async, so
    the graph must be driven with ainvoke() rather than invoke().

    Args:
        user_query (str): The question to answer.

    Returns:
        AgentState: The answer plus the trace of tool calls behind it.
    """
    result = await app.ainvoke({"user_query": user_query})
    return AgentState(
        user_query=user_query,
        answer=result["answer"],
        tool_calls=result.get("tool_calls") or [],
    )


# --- Cluster Checks -------------------------------------------------------
# The Operations Dashboard's "Trigger Checks" button. This is two passes: the
# agent runs the checks and follows its own findings up with further tools,
# then a second, tool-free LLM call reads the resulting trace back and writes
# one verdict per tool call. The second pass exists because the dashboard needs
# the findings attached to the calls that produced them — recovering that from
# the agent's prose answer would be guesswork.

CLUSTER_CHECKS_QUERY = """
Run a health and performance review of this Couchbase cluster, in three steps.

Step 1 - baseline checks. Call the matching tool for each of these, one call per check:
1) cluster connection, 2) cluster health and services, 3) long-running queries,
4) queries that are not selective, 5) queries that do not use a covering index,
6) queries that use only the primary index, 7) queries with the largest response sizes,
8) queries with the largest result counts.

Step 2 - follow up on what you found. IMPORTANT: call tools immediately in this step — do NOT
write any intermediate analysis or planning text first. The agent loop ends the moment you output
text without a tool call, so make every follow-up tool call before writing anything.
Identify how the baseline findings relate to one another (the same statement appearing as both
long-running and non-selective is one problem, not two), then immediately call the tools:
- For a slow, non-selective, or primary-index query: call get_index_advisor_recommendations
  for the query statement that ran the longest, then call explain_sql_plus_plus_query for it.
- For a degraded service: call get_server_configuration_status.
Do not run follow-up tools for checks that came back clean, and do not repeat a call you have already made.

Step 3 - report. For each problem, say what it is, which tool call shows it, whether it is the
same underlying cause as another finding, and what should be done about it. Quote the concrete
statements, durations, index names and counts the tools returned. If every check came back clean,
say so plainly.
"""


REPORT_SYSTEM_PROMPT = """
You are a Couchbase operations analyst writing up a cluster check that has already run.

You are given the agent's own summary of the run and the numbered trace of every tool call it
made, with the arguments and the raw result of each. Return one entry per tool call, in order,
identified by the number it carries in the trace. Judge each call on its own result.

severity:
- "critical" - the cluster, a node or a service is unavailable, failing, or at risk of data loss.
- "serious"  - performance is measurably degraded: a long-running statement, a primary-index
               scan, a non-selective scan, an oversized response or result count.
- "warning"  - worth watching but not yet hurting: a missing covering index on a cheap query,
               a configuration that will not scale, a result close to a limit.
- "none"     - the call came back clean, or it was a follow-up call made only to gather context
               for another finding.

finding: at most three sentences of plain English saying what this call shows, naming the
concrete statements, durations, index names and counts from its result. Empty when severity
is "none".

recommendation: at most three sentences saying what to do about it. Ground it in the follow-up
calls in the trace - the index the advisor suggested, the plan that shows a primary scan, the
indexes that already exist - and say when this finding shares an underlying cause with an
earlier one. Empty when there is nothing to act on.

Never invent a number, statement, index or service name that is not in the trace.
"""

# How much of each tool result the reporting pass is shown. Query-diagnostics
# results run to tens of kilobytes; the head carries the statements and timings
# the verdict is written from.
RESULT_CHARS_FOR_REPORT = 3000


class ToolCallFinding(BaseModel):
    """One tool call's verdict, written by the reporting pass."""

    tool_call: int = Field(description="1-based position of this call in the numbered trace")
    severity: Literal["critical", "serious", "warning", "none"] = Field(
        description="'none' when the call surfaced nothing worth reporting"
    )
    finding: str = Field(description="At most three sentences; empty when severity is 'none'")
    recommendation: str = Field(description="At most three sentences; empty when there is nothing to act on")


class CheckReport(BaseModel):
    """The reporting pass's read of a whole check run."""

    summary: str = Field(description="One or two sentences on the state of the cluster overall")
    findings: list[ToolCallFinding] = Field(description="One entry per tool call, in trace order")


class CheckRun(TypedDict):
    """A completed check run, as the dashboard consumes it."""

    answer: str
    summary: str
    tool_calls: list[AnnotatedToolCall]
    counts: dict[str, int]


def _render_trace(tool_calls: list[ToolCallTrace]) -> str:
    """Number the trace so the reporting pass can point at individual calls."""
    blocks: list[str] = []
    for index, call in enumerate(tool_calls, start=1):
        result = call["result"] or "(the tool returned no result)"
        if len(result) > RESULT_CHARS_FOR_REPORT:
            omitted = len(result) - RESULT_CHARS_FOR_REPORT
            result = f"{result[:RESULT_CHARS_FOR_REPORT]}\n… [{omitted} more characters omitted]"
        blocks.append(
            f"Tool call {index}: {call['name']}\n"
            f"Arguments: {json.dumps(call['args'], default=str)}\n"
            f"Status: {call['status']}\n"
            f"Result:\n{result}"
        )
    return "\n\n".join(blocks)


async def analyse_check_run(answer: str, tool_calls: list[ToolCallTrace]) -> CheckReport:
    """Reads a finished run's trace back and writes one verdict per tool call.

    No tools are bound here: the pass only reads what the run already returned,
    so it cannot go back to the cluster for anything the agent did not fetch.

    Args:
        answer (str): The agent's own prose summary of the run.
        tool_calls (list[ToolCallTrace]): The run's trace, in the order made.

    Returns:
        CheckReport: An overall summary plus a verdict per tool call.
    """
    if not tool_calls:
        return CheckReport(summary=answer.strip() or "The check run made no tool calls.", findings=[])

    reporter = llm.with_structured_output(CheckReport)
    return await reporter.ainvoke(
        [
            SystemMessage(content=REPORT_SYSTEM_PROMPT),
            HumanMessage(
                content=(
                    f"The agent summarised the run like this:\n{answer}\n\n"
                    f"Trace of all {len(tool_calls)} tool calls:\n\n{_render_trace(tool_calls)}"
                )
            ),
        ]
    )


async def run_cluster_checks() -> CheckRun:
    """
    Runs the dashboard's cluster checks and reports on them.

    The agent runs the baseline checks, then follows its own findings up with
    whatever further tools they call for — the index advisor on a slow
    statement, the indexes on the collection it reads — before a second pass
    attaches a severity, a finding and a recommendation to each call it made.

    Returns:
        CheckRun: The agent's answer, an overall summary, the annotated trace,
            and how many calls landed at each severity.
    """
    run = await run_agent(CLUSTER_CHECKS_QUERY)
    report = await analyse_check_run(run["answer"], run["tool_calls"])

    annotated: list[AnnotatedToolCall] = [dict(call) for call in run["tool_calls"]]
    for verdict in report.findings:
        index = verdict.tool_call - 1
        # The pass is asked for one entry per call, by number. An entry pointing
        # outside the trace is dropped rather than shifted onto a neighbouring
        # call, which would put a finding against a tool that never ran.
        if not 0 <= index < len(annotated):
            continue

        finding = verdict.finding.strip()
        # A severity with nothing to say behind it would colour a tool call the
        # dashboard then has to label "No findings.", so both are needed.
        if verdict.severity == "none" or not finding:
            continue

        annotated[index]["severity"] = verdict.severity
        annotated[index]["finding"] = finding
        recommendation = verdict.recommendation.strip()
        if recommendation:
            annotated[index]["recommendation"] = recommendation

    counts = {
        severity: sum(1 for call in annotated if call.get("severity") == severity)
        for severity in ("critical", "serious", "warning")
    }
    return CheckRun(
        answer=run["answer"],
        summary=report.summary.strip(),
        tool_calls=annotated,
        counts=counts,
    )


# --- Run the App ---
if __name__ == "__main__":
    query = input("Input user query: ")
    run = asyncio.run(run_agent(query))
    print(run["answer"])