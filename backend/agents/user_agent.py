import asyncio
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, TypedDict
from dotenv import load_dotenv
from langgraph.graph import StateGraph, END, START
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool
from mcp import ClientSession
from agentmemory import AgentMemoryError, AsyncAgentMemoryClient, AsyncSessionResource

from services import memory

logger = logging.getLogger(__name__)

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
            "CB_MCP_READ_ONLY_MODE": "true",
            "CB_MCP_DISABLED_TOOLS": "get_server_configuration_status,test_cluster_connection,get_cluster_health_and_services,upsert_document_by_id,insert_document_by_id,replace_document_by_id,delete_document_by_id,explain_sql_plus_plus_query,list_indexes,get_index_advisor_recommendations,get_longest_running_queries,get_most_frequent_queries,get_queries_not_selective,get_queries_not_using_covering_index,get_queries_using_primary_index,get_queries_with_largest_response_sizes,get_queries_with_large_result_count"
        }
    }
}


# --- Keep the MCP server running between questions ---
# A shopper's conversation is many short turns, and starting the server costs
# seconds each time (uvx, a fresh interpreter, a new cluster connection). So it
# is started once and reused; the admin agent, whose runs are long and rare,
# still starts its own per request.
MCP_PING_TIMEOUT_SECONDS = 5.0
MCP_SHUTDOWN_TIMEOUT_SECONDS = 10.0


class PersistentMCPSession:
    """One long-lived MCP server session, restarted if it stops responding.

    The session is an anyio context manager, which must be exited by the task
    that entered it. Requests and the app lifespan run in different tasks, so a
    dedicated owner task holds the session open until it is told to stop.
    """

    def __init__(self, client: MultiServerMCPClient, server_name: str) -> None:
        self._client = client
        self._server_name = server_name
        # Serialises start/restart: two questions arriving at a dead server
        # must not each spawn a replacement.
        self._lock = asyncio.Lock()
        self._owner: asyncio.Task[None] | None = None
        self._stop: asyncio.Event | None = None
        self._session: ClientSession | None = None
        self._tools: list[BaseTool] | None = None

    async def tools(self) -> list[BaseTool]:
        """Return the server's tools, starting or restarting the server if needed."""
        async with self._lock:
            if self._tools is not None and await self._alive():
                return self._tools
            if self._owner is not None:
                logger.warning("MCP server %r stopped responding; restarting it.", self._server_name)
            await self._shutdown()
            await self._start()
            return self._tools

    async def close(self) -> None:
        """Stop the server; the next call to tools() starts a fresh one."""
        async with self._lock:
            await self._shutdown()

    async def _alive(self) -> bool:
        # A ping catches a server that died between questions — its pipe is
        # closed, so the request fails fast instead of mid-way through a run.
        if self._owner is None or self._owner.done():
            return False
        try:
            await asyncio.wait_for(self._session.send_ping(), MCP_PING_TIMEOUT_SECONDS)
        except Exception:
            return False
        return True

    async def _start(self) -> None:
        ready: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        stop = asyncio.Event()

        async def own() -> None:
            try:
                async with self._client.session(self._server_name) as session:
                    tools = await load_mcp_tools(session)
                    # State is set here rather than by the caller, so it still
                    # lands if the request that started the server went away.
                    self._session, self._tools = session, tools
                    print("")
                    print(f"Started MCP server, loaded {len(tools)} tools: {[t.name for t in tools][:5]} ...")
                    print("")
                    ready.set_result(None)
                    await stop.wait()
            except Exception as exc:
                if not ready.done():
                    ready.set_exception(exc)
                else:
                    # Tearing down a server that already died can fail too;
                    # it is gone either way.
                    logger.debug("MCP server %r exited uncleanly.", self._server_name, exc_info=True)
            finally:
                # Cancelled before the server came up: release the waiter
                # rather than leave it hanging on a future nobody will resolve.
                if not ready.done():
                    ready.cancel()

        self._owner = asyncio.create_task(own())
        self._stop = stop
        # Shielded so a cancelled caller does not cancel `ready` itself, which
        # would make set_result() raise and tear down a server that came up fine.
        await asyncio.shield(ready)

    async def _shutdown(self) -> None:
        owner, stop = self._owner, self._stop
        self._owner = self._stop = self._session = self._tools = None
        if owner is None:
            return
        stop.set()
        await asyncio.wait({owner}, timeout=MCP_SHUTDOWN_TIMEOUT_SECONDS)
        if not owner.done():
            owner.cancel()
            await asyncio.wait({owner})


mcp_server = PersistentMCPSession(MultiServerMCPClient(MCP_SERVERS), "couchbase")


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
class AgentState(TypedDict):
    user_query: str
    # Memories recalled for this turn, already flattened to display text. Empty
    # for signed-out shoppers, for whom the assistant stays stateless.
    memories: list[str]
    answer: str
    # The Agent Memory session this turn belonged to; None when memory is off.
    session_id: str | None
    # The retention this session's message memories are actually running with.
    retention_seconds: int | None


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


# --- Tool call tracing ---
# Tool results are whole SQL++ result sets, so they are clipped in the terminal
# rather than scrolling the run off the screen. Raise it to see more.
TOOL_RESULT_PRINT_LIMIT = 2000


def _clip(text: str, limit: int = TOOL_RESULT_PRINT_LIMIT) -> str:
    """Shorten text for the terminal, saying how much was left out."""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n... [{len(text) - limit} more characters]"


def _indent(text: str, prefix: str = "      ") -> str:
    """Indent every line so multi-line args and results stay inside their block."""
    return "\n".join(f"{prefix}{line}" for line in text.splitlines()) or f"{prefix}"


def _print_tool_calls(messages: list[Any]) -> None:
    """Print every tool the agent called this run, with its args and its result.

    The agent loop leaves an interleaved transcript: an AIMessage carrying
    `tool_calls`, then one ToolMessage per call, referencing the call it answers
    by id. Results are indexed by id first, then the transcript is walked in
    order so the calls print in the sequence the agent made them.

    This runs once the agent has finished, so the whole trace appears after the
    answer is produced rather than live as each tool returns.
    """
    results_by_id: dict[str, ToolMessage] = {
        message.tool_call_id: message
        for message in messages
        if isinstance(message, ToolMessage)
    }

    calls = [
        call
        for message in messages
        for call in (getattr(message, "tool_calls", None) or [])
    ]

    print("")
    print(f"--- TOOL CALLS ({len(calls)}) ---")
    if not calls:
        print("(the agent answered without calling any tool)")
        print("")
        return

    for index, call in enumerate(calls, start=1):
        result = results_by_id.get(call.get("id"))
        # A call with no matching ToolMessage never returned — the run was cut
        # short (recursion limit, error) before the tool replied.
        status = (getattr(result, "status", "success") or "success") if result else "pending"
        print("")
        print(f"[{index}] {call.get('name') or '<unnamed>'}  (status: {status})")
        print("    args:")
        print(_indent(json.dumps(call.get("args") or {}, indent=2, default=str)))
        print("    result:")
        print(_indent(_clip(_stringify_content(result.content) if result else "")))
    print("")


# --- Define Couchbase Agent ---
COUCHBASE_SYSTEM_PROMPT = f"""
    You are a customer assistant. Answer questions about the data stored in the database by calling the available Couchbase tools - never guess at data.
    If a query returns 0 rows, you MUST NOT answer using information from your context or prior memory — say the product or data was not found and offer to search differently.
    If the customer asks you to add, modify or delete data - politely answer that you cannot perform those actions.
    Never show any information about the cluster to the customer, such as bucket, scope or collection names, their quantity etc.
    Never recommend customers an SQL++ query to search for something.
    Never write a document ID or a sku out as visible text — the only place one may appear is inside a product link, as described below.

    Default target for this application:
    bucket:     {os.getenv("COUCHBASE_BUCKET")}
    scope:      {os.getenv("COUCHBASE_SCOPE")}
    collection: {os.getenv("COUCHBASE_COLLECTION")}
    FTS index:  {os.getenv("COUCHBASE_FTS_INDEX")}

    Always inspect the collection schema before writing a query. Never assume field names for a query instead of actually looking them up.  
    If the question includes the description of the product, e.g. "Find 5 products with floral print", use the FTS SEARCH function within the SQL++ query like this: 
    "SELECT p.meta().id, p.description FROM `webshop`.`webshop-scope`.`products` AS p WHERE SEARCH(p.description, "floral print") ORDER BY SEARCH_SCORE() DESC
    LIMIT 5; "
    Always return relevant fields including the document ID within the SELECT statement of SQL++ (example: "SELECT meta().id, sku, name, price.amount, price.currency FROM `webshop`.`webshop-scope`.`products` WHERE category.subtype = 'Blouses' AND price.amount < 30 AND price.currency = 'EUR' LIMIT 1;"). 
    Always use the fully qualified keyspace `bucket`.`scope`.`collection` in SQL++ queries. 
    Answer in plain English.

    Linking products:
    Always select the product's `sku` field in your queries, alongside meta().id.
    Every time you name a product from the catalogue, write its name as a markdown link to that product's page:
    [Product Name](/products/<sku>), using the sku exactly as it came back from the query — the bare sku, with no "product::" prefix.
    For example: [Vertical Stripe Long-Sleeve Shirt](/products/SHIRT-STR-NVY-001).
    Link a product the first time you name it in an answer; later mentions of the same product in that answer can stay plain text.
    Never invent a link — only link a product whose sku came back from a tool call.
"""

async def user_agent(state: AgentState) -> dict:
    """
    Answers questions about products stored in the Couchbase cluster.

    Runs a ReAct-style agent whose tools are supplied at runtime by the Couchbase
    MCP Server (document lookup by ID, SQL++ execution).

    Args:
        state (AgentState): A dictionary with the user's query and the memories
            recalled for it.

    Returns:
        dict: Updated state with the generated answer.
    """
    print("")
    print("--- Couchbase Node ---")
    # Recalled memories ride on the system prompt rather than the message list:
    # they are background the agent may draw on, not a turn it has to answer.
    system_prompt = COUCHBASE_SYSTEM_PROMPT + memory.memory_context(state["memories"])
    print("")
    print("--- AGENT SYSTEM PROMPT ---")
    print(system_prompt)
    # The server outlives this run (see PersistentMCPSession); the agent itself
    # is rebuilt each turn because its system prompt carries this turn's memories.
    tools = await mcp_server.tools()
    agent = create_agent(llm, tools, system_prompt=system_prompt)
    result = await agent.ainvoke({"messages": state["user_query"]})
    _print_tool_calls(result["messages"])
    print("")
    print("--- AGENT RESULT CONTENT ---")
    print(result["messages"][-1].content)
    print("")
    return {"answer": _stringify_content(result["messages"][-1].content)}


# --- Build the Graph ---
# user_agent is the only node, so there is nothing to route between.
workflow = StateGraph(AgentState)
workflow.add_node("user_agent", user_agent) # Adds the MCP-backed agent
workflow.add_edge(START, "user_agent")
workflow.add_edge("user_agent", END)

app = workflow.compile()


# Detached fact-extraction tasks. asyncio holds only a weak reference to a bare
# task, so one not kept here can be garbage-collected before it finishes.
_FACT_TASKS: set[asyncio.Task[None]] = set()


async def _store_facts_detached(
    client: AsyncAgentMemoryClient,
    session: AsyncSessionResource,
    user_query: str,
    answer: str,
    *,
    created_at: str | None,
) -> None:
    """Judge and store durable facts after the shopper has their answer.

    Runs off the request path: the judge is an LLM call and the write waits on
    server-side processing, and neither this turn nor the next needs the result
    — facts feed cross-visit recall, where seconds of delay cost nothing. The
    exchange itself is still written synchronously, because a follow-up like
    "the black one" is answered from it.

    Owns `client` and closes it. The request path hands ownership over rather
    than closing it itself, since `session` is bound to it and would be unusable
    the moment it shut.
    """
    try:
        facts = await memory.judge_facts(user_query, answer)
        if facts:
            print(f"Stored {len(facts)} fact(s): {facts}")
            await memory.record_facts(session, facts, created_at=created_at)
    except Exception:
        # Guarded against every failure, not just memory ones: the judge is an
        # LLM call, and nothing here may surface to the shopper, who has long
        # since been given their answer.
        logger.exception("Fact extraction failed for session_id=%r", session.session_id)
    finally:
        await client.close()


async def run_agent(
    user_query: str,
    user_id: str | None = None,
    username: str | None = None,
    session_id: str | None = None,
    turn_count: int = 0,
    created_at: str | None = None,
    retention_seconds: int | None = None,
) -> AgentState:
    """
    Runs the compiled graph for a single query and returns its final state.

    This is the entry point the FastAPI layer calls; MCP tools are async, so
    the graph must be driven with ainvoke() rather than invoke().

    One turn is: ensure user -> ensure session -> search memory -> answer with
    what came back -> store the exchange. Signed-out shoppers skip all of it and
    get a stateless assistant, since there is no identity to file memories under
    and pooling anonymous visitors would leak their conversations to each other.

    Args:
        user_query (str): The question to answer.
        user_id (str | None): The signed-in shopper. None turns memory off.
        username (str | None): The shopper's human-readable name, used only to
            label the Agent Memory user on first creation. Falls back to user_id.
        session_id (str | None): The conversation's session, echoed back from a
            previous turn. None opens a new one.
        turn_count (int): Turns this conversation has already had, echoed back
            from the previous turn. Selects the shape of recall.
        created_at (str | None): The timestamp memories written this turn are
            attributed to, when a presenter has dated the session into the past.
            None files them at the time they were recorded.
        retention_seconds (int | None): How long this session's message memories
            should survive. Only applies on the turn that opens the session.

    Returns:
        AgentState: The answer and the session it was filed under.
    """
    if not user_id:
        result = await app.ainvoke({"user_query": user_query, "memories": []})
        return AgentState(
            user_query=user_query,
            memories=[],
            answer=result["answer"],
            session_id=None,
            retention_seconds=None,
        )

    client = memory.memory_client()
    session: AsyncSessionResource | None = None
    memories: list[str] = []
    # Set once the fact task has taken ownership of `client`, so the `finally`
    # below knows not to close a client still in use.
    facts_detached = False
    try:
        try:
            user = await memory.ensure_user(client, user_id, username)
            session = await memory.ensure_session(
                user, session_id, retention_seconds=retention_seconds
            )
            memories = await memory.recall(
                session, user_query, turn_count=turn_count
            )
            print("")
            print(f"Recalled {len(memories)} memories for session {session.session_id}")
            print("")
        except AgentMemoryError:
            # Memory is an enhancement, not a dependency: if the server is down
            # the shopper still gets their answer, just without recall.
            logger.exception("Agent memory recall failed for user_id=%r", user_id)

        result = await app.ainvoke({"user_query": user_query, "memories": memories})
        answer = result["answer"]

        if session is not None:
            # The exchange is recorded first and on its own guard: a failure in
            # the fact path below must not cost the transcript.
            try:
                await memory.record_turn(
                    session, user_query, answer, created_at=created_at
                )
            except AgentMemoryError:
                logger.exception(
                    "Agent memory write failed for session_id=%r", session.session_id
                )

            # Judging is detached rather than awaited: it is an LLM call plus a
            # synchronous write, and the shopper would otherwise wait out both
            # to be handed an answer that is already final. The task takes over
            # the client, so it outlives this block.
            task = asyncio.create_task(
                _store_facts_detached(
                    client, session, user_query, answer, created_at=created_at
                )
            )
            _FACT_TASKS.add(task)
            task.add_done_callback(_FACT_TASKS.discard)
            facts_detached = True
    finally:
        if not facts_detached:
            await client.close()

    return AgentState(
        user_query=user_query,
        memories=memories,
        answer=answer,
        session_id=session.session_id if session is not None else None,
        # What the session is actually running with, read off the session rather
        # than echoed from the request: on any turn but the first the requested
        # value was ignored, and the panel must show what is in force.
        # getattr because this line sits outside the guards above: memory must
        # never be the reason a shopper loses an answer, least of all over a
        # field that is only used to label a control in the panel.
        retention_seconds=getattr(session, "blocks_ttl", None),
    )


# --- Run the App ---
if __name__ == "__main__":
    query = input("Input user query: ")

    async def _main() -> AgentState:
        try:
            return await run_agent(query)
        finally:
            await mcp_server.close()

    run = asyncio.run(_main())
    print(run["answer"])