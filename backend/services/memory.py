"""Agent Memory policy for the shopper-facing assistant.

Everything about what the assistant remembers lives here: how long each kind of
memory survives, what is recalled on a turn, and how recalled memories are
rendered into the agent's prompt. `agents/user_agent.py` calls in and stays a
readable sequence.

The split matters because the two kinds of memory are governed differently. A
conversational turn is a transcript entry that decays; a fact the shopper stated
about themselves is durable. The Agent Memory server keeps both in one store and
distinguishes them by annotation, so almost every rule below is really a rule
about which of the two is being handled.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path

from dotenv import load_dotenv

from agentmemory import (
    AsyncAgentMemoryClient,
    ChatMessage,
    AsyncSessionResource,
    AsyncUserResource,
    ConflictError,
    MemoryBlock,
    NotFoundError,
)

logger = logging.getLogger(__name__)

# Loaded here as well as in user_agent, because this module is importable on its
# own (tests, scripts) and its configuration comes from the same file.
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(ENV_PATH)


def _int_env(name: str, default: int) -> int:
    """Read an integer setting, falling back to `default` when unset or unusable.

    A malformed value is a configuration mistake, not a reason to refuse to
    start: the assistant runs on the default and says so once in the log.
    """
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("%s=%r is not an integer; using %d", name, raw, default)
        return default


# --- Configuration -----------------------------------------------------------
# Read once, at import, and exposed as module constants so tests and scripts can
# read the same values the assistant is running on.

AGENT_MEMORY_URL = os.getenv("AGENT_MEMORY_URL", "http://localhost:8080")

# Retention. Conversational turns decay; facts do not. A TTL of 0 means no
# expiry, and per-block TTL overrides the session default — which is what lets a
# short-lived session still hold permanent facts.
MESSAGE_BLOCK_TTL_SECONDS = _int_env("MEMORY_MESSAGE_TTL_SECONDS", 90 * 24 * 60 * 60)
FACT_BLOCK_TTL_SECONDS = _int_env("MEMORY_FACT_TTL_SECONDS", 0)

# Recall shape. Turns inside the window are given to the agent verbatim so a
# follow-up like "the black one" can still be resolved; older turns are
# compressed. Past the threshold the whole conversation is no longer fetched and
# recall becomes a semantic search.
VERBATIM_WINDOW_TURNS = _int_env("MEMORY_VERBATIM_WINDOW_TURNS", 3)
SEARCH_THRESHOLD_TURNS = _int_env("MEMORY_SEARCH_THRESHOLD_TURNS", 10)

# Fact extraction. The category list is closed on purpose: an open-ended prompt
# invites the model to file conversational trivia as durable shopper facts.
FACT_CATEGORIES = (
    "clothing or shoe size",
    "favourite or preferred brand",
    "preferences in clothing or shoe designs",
    "colour preference or dislike",
    "budget or price range",
    "occasion or purpose they are shopping for",
)
# Bounds on what the judge is allowed to store, applied before any write.
MAX_FACTS_PER_TURN = _int_env("MEMORY_MAX_FACTS_PER_TURN", 3)
MAX_FACT_LENGTH = _int_env("MEMORY_MAX_FACT_LENGTH", 200)

# Cross-session recall budgets. Facts and turns are searched separately and get
# their own allowance, so a chatty past session cannot crowd out a stated
# preference. Facts are short and high-value; turns are long, so theirs is the
# one worth keeping tight.
CROSS_SESSION_FACT_K = _int_env("MEMORY_CROSS_SESSION_FACT_K", 10)
CROSS_SESSION_TURN_K = _int_env("MEMORY_CROSS_SESSION_TURN_K", 10)

# Annotation values marking what a block is. These are load-bearing: cross-session
# recall filters on them, so a block written without one is unreachable.
ANNOTATION_KEY = "type"
TYPE_TURN = "turn"
TYPE_FACT = "fact"


def memory_client() -> AsyncAgentMemoryClient:
    """Open a client against the Agent Memory server. Caller closes it."""
    return AsyncAgentMemoryClient(base_url=AGENT_MEMORY_URL)


# --- Session lifecycle -------------------------------------------------------
# Pulls the n out of an existing session id so the next one can carry n + 1.
_SESSION_INDEX = re.compile(r"session(\d+)", re.IGNORECASE)


def _new_session_id(user_id: str, existing_session_ids: list[str]) -> str:
    """Mint the id for a shopper's next session: `session{n}`.

    `n` starts at 1 and is read back off the ids already stored rather than from
    how many there are, so deleting a session cannot hand its number to a later
    one and collide.

    The id must not contain `/`: it is interpolated straight into
    `/users/{user_id}/sessions/{session_id}`, so a slash silently becomes extra
    path segments and the request stops matching the route (the server answers
    `{"detail": "Not Found"}`). Percent-encoding does not help — the server
    decodes before it routes.
    """
    highest = 0
    for session_id in existing_session_ids:
        found = _SESSION_INDEX.search(session_id)
        if found:
            highest = max(highest, int(found.group(1)))

    return f"session{highest + 1}"


async def ensure_user(
    client: AsyncAgentMemoryClient, user_id: str, username: str | None = None
) -> AsyncUserResource:
    """Fetch the shopper's Agent Memory user, creating it on first ever visit.

    `user_id` is the identity memories are filed under; `username` is only the
    human-readable label stored alongside it, so a caller that does not know the
    username falls back to the id rather than failing the turn. The name is set
    once, at creation — renaming an existing user is not what this does.
    """
    try:
        return await client.get_user(user_id)
    except NotFoundError:
        try:
            return await client.create_user(user_id=user_id, name=username or user_id)
        except ConflictError:
            # Two first turns raced each other; whoever lost just reads the user
            # the winner created.
            return await client.get_user(user_id)


async def ensure_session(
    user: AsyncUserResource,
    session_id: str | None,
    *,
    retention_seconds: int | None = None,
) -> AsyncSessionResource:
    """Resume the conversation's session, or open a new one for its first turn.

    The caller holds the session id for the life of one chat conversation and
    passes it back on every later turn, so a new session is minted only when it
    arrives as None — which is exactly when the panel was opened, closed and
    reopened, or the shopper signed in or out.

    `retention_seconds` sets how long this session's message blocks survive, and
    can therefore only apply to the request that opens the session. On any later
    turn the session already exists and the value has nowhere to go, so it is
    ignored rather than silently reinterpreted.
    """
    if session_id:
        return await user.get_session(session_id)

    ttl = MESSAGE_BLOCK_TTL_SECONDS if retention_seconds is None else retention_seconds
    return await user.create_session(
        session_id=_new_session_id(user.user_id, user.sessions or []),
        memory_blocks_ttl=ttl,
    )


# --- Rendering ---------------------------------------------------------------
def render_fact(block: MemoryBlock) -> str:
    """Render a recalled fact, with the time the shopper stated it.

    The timestamp is what lets the agent resolve contradictions: the server
    stores it but does not act on it, so the prompt has to carry it. `created_at`
    is the shopper's own timeline — a session dated into the past sets it — and
    `ingested_at` is only the fallback for a block that somehow has no
    `created_at`.
    """
    stated_at = (block.created_at or block.ingested_at or "").strip()
    day = stated_at.split("T")[0] if stated_at else ""
    return f"{block.fact} (stated {day})" if day else str(block.fact)


def render_turn(block: MemoryBlock, *, verbatim: bool) -> str:
    """Render a recalled exchange, either in full or compressed.

    Compressed rendering walks a ladder: the extracted context lines, then the
    generated summary, then the exchange itself. The last rung is not optional —
    a block whose extraction failed is still returned by search with both fields
    empty, and it must not contribute a blank line to the prompt.
    """
    message = block.message
    full = (
        f"User asked: {message.user_content}\nAgent answered: {message.assistant_content}"
        if message
        else ""
    )
    if verbatim:
        return full

    if block.contexts:
        # Every context line is kept. Extraction is already the compression
        # step, and filtering it further was tried and reverted: the line
        # carrying the concrete product names ("The list includes Men's Light
        # Blue Slim Jeans, ...") reads as generic prose to any cheap heuristic,
        # so dropping it destroyed exactly the referent a later "the black one"
        # needs. A few extra tokens are worth far less than that.
        return "Earlier: " + "; ".join(block.contexts)
    if block.summary:
        return f"Earlier: {block.summary}"
    return full


def render_block(block: MemoryBlock, *, verbatim: bool = True) -> str:
    """Render one recalled block as prompt text."""
    if block.fact:
        return render_fact(block)
    if block.message:
        return render_turn(block, verbatim=verbatim)
    return ""


def render_recalled(blocks: list[MemoryBlock], *, verbatim_turns: int) -> list[str]:
    """Render recalled blocks into prompt lines, newest-first input, oldest-first out.

    `verbatim_turns` is counted in exchanges, not blocks, so facts recalled
    alongside them never consume the window. Chronological order is restored on
    the way out because the prompt reads as a history.
    """
    lines: list[str] = []
    turns_seen = 0
    for block in blocks:
        if block.message and not block.fact:
            turns_seen += 1
            line = render_turn(block, verbatim=turns_seen <= verbatim_turns)
        else:
            line = render_block(block)
        if line.strip():
            lines.append(line)

    return list(reversed(lines))


def memory_context(memories: list[str]) -> str:
    """Render recalled memories as a system-prompt suffix for this turn."""
    if not memories:
        return ""

    recalled = "\n".join(f"- {memory}" for memory in memories)
    return (
        "\n\n    --- What you already know about this shopper, from this conversation "
        "and from their earlier visits --- \n\n"
        f"{recalled}\n"
        "    Use these when they help answer the question and ignore them when "
        "they do not. Never tell the customer that you are consulting stored "
        "memories, and never repeat one back as if it were new information.\n"
        "    Some of these are dated. Where two of them contradict each other — "
        "the same preference stated two different ways — act on the most recently "
        "stated one and disregard the older, because the customer has changed "
        "their mind. Never ask the customer to confirm which is current.\n"
        "    These memories are a record of past conversations, not catalogue "
        "data. A product named in them may have changed price, changed size "
        "availability, or been withdrawn. So treat any product mentioned here as "
        "a lead to check, never as a result: verify it with an SQL++ query "
        "before you name it. Product names in memory may be abbreviated — use "
        "LIKE with wildcards (e.g. WHERE name LIKE '%cap-sleeve%') rather than "
        "exact equality. Take price, sku and sizes only from what the query "
        "returns. If the query returns 0 rows, you MUST NOT name that product, "
        "provide its price, or mention its size — say it is no longer available "
        "and offer to search for alternatives instead. Never construct or guess "
        "a document ID — document IDs are not derivable from product names or "
        "descriptions. Never write a product link whose sku came from a memory "
        "rather than from a tool call.\n"
    )


# --- Fact extraction ------------------------------------------------------
_FACT_JUDGE_PROMPT = """You extract durable facts about a shopper from one exchange with a shop assistant.

A durable fact is something about the shopper that stays true after this conversation ends, and only in these categories:
{categories}

Rules:
- Only record what the SHOPPER stated about themselves. Never record what the assistant said, what products exist, or what was shown to them.
- A question is not a fact. "do you have jeans under 50 EUR?" states no budget preference.
- Write each fact as one short third-person sentence, starting with "The shopper".
- If the exchange contains no durable fact, return an empty list.

Return ONLY a JSON array of strings, with no explanation and no code fence. Examples:
["The shopper's usual size is M."]
[]

Exchange:
Shopper: {query}
Assistant: {answer}"""


def _judge_llm():
    """Build the LLM used to judge facts, lazily.

    Separate from the agent's own LLM so the judge can be pointed at a cheaper
    model without touching the assistant, and so importing this module does not
    require the agent's configuration. Switch it the same way the agents are
    switched (see agents/user_agent.py): comment out one block, uncomment the
    other. The judge only has to emit a short JSON array, so it is the safest
    of the three to move first.
    """
    from langchain_openai import ChatOpenAI

    # If OpenAI model is used
    return ChatOpenAI(model=os.getenv("OPEN_AI_MODEL"), temperature=0)
    # If Capella-hosted LLM is used
    # return ChatOpenAI(
    #     model=os.getenv("LLM_MODEL"),
    #     base_url=os.getenv("LLM_BASE_URL"),
    #     api_key=os.getenv("LLM_API_KEY"),
    #     temperature=0,
    # )


def validate_facts(raw: object) -> list[str]:
    """Reduce whatever the judge returned to facts that are safe to store.

    The judge is an LLM asked for JSON, so its output is untrusted input: prose,
    a bare string, a nested object or a hundred items are all possible. Anything
    that is not a list of short non-blank strings is discarded rather than
    repaired, because a half-understood fact is worse than none.
    """
    if not isinstance(raw, list):
        return []

    facts: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        fact = item.strip()
        if not fact or len(fact) > MAX_FACT_LENGTH:
            continue
        if fact in facts:
            continue
        facts.append(fact)

    return facts[:MAX_FACTS_PER_TURN]


def _parse_judge_output(text: str) -> list[str]:
    """Pull the JSON array out of the judge's reply, tolerating a code fence."""
    import json

    cleaned = text.strip()
    if cleaned.startswith("```"):
        # ```json\n[...]\n``` — drop the fence lines, keep the body.
        lines = [line for line in cleaned.splitlines() if not line.startswith("```")]
        cleaned = "\n".join(lines).strip()

    try:
        return validate_facts(json.loads(cleaned))
    except (ValueError, TypeError):
        logger.warning("Fact judge returned unparseable output: %r", text[:200])
        return []


async def judge_facts(query: str, answer: str, *, llm=None) -> list[str]:
    """Decide which durable shopper facts, if any, this exchange contained.

    Runs after the shopper already has their answer, so its latency is invisible
    to them. Returns an empty list for the common case of a turn that stated
    nothing durable.
    """
    prompt = _FACT_JUDGE_PROMPT.format(
        categories="\n".join(f"- {c}" for c in FACT_CATEGORIES),
        query=query,
        answer=answer,
    )
    model = llm if llm is not None else _judge_llm()
    result = await model.ainvoke(prompt)
    content = getattr(result, "content", result)
    if not isinstance(content, str):
        content = str(content)
    return _parse_judge_output(content)


# --- Recall and record -------------------------------------------------------
# The server caps one listing page at 200 blocks, and refuses more.
_LIST_PAGE_LIMIT = 200
# Ceiling on how much of a session is ever pulled back in one turn, so a very
# long conversation cannot balloon the prompt or the number of requests.
MAX_SESSION_BLOCKS = _int_env("MEMORY_MAX_SESSION_BLOCKS", 200)


async def _list_session_blocks(
    session: AsyncSessionResource, *, cap: int = MAX_SESSION_BLOCKS
) -> list[MemoryBlock]:
    """Fetch a session's blocks newest-first, paging past the default limit.

    `list_memories` defaults to 20 per page, so a session holding more than that
    would silently come back truncated. Paging continues until the server's
    reported total is covered or `cap` is reached.
    """
    blocks: list[MemoryBlock] = []
    offset = 0
    while len(blocks) < cap:
        page_size = min(_LIST_PAGE_LIMIT, cap - len(blocks))
        page = await session.list_memories(limit=page_size, offset=offset)
        blocks.extend(page.memory_blocks)
        total = page.total or len(blocks)
        if not page.memory_blocks or len(blocks) >= total:
            break
        offset = len(blocks)

    return blocks[:cap]


async def _recent_blocks(
    session: AsyncSessionResource, *, turns: int
) -> list[MemoryBlock]:
    """Fetch enough of the newest blocks to cover `turns` exchanges.

    Facts share the session with exchanges and are returned by the same listing,
    so more blocks than turns are requested to leave room for them.
    """
    if turns <= 0:
        return []
    limit = min(_LIST_PAGE_LIMIT, turns * 3 + 3)
    page = await session.list_memories(limit=limit)
    return list(page.memory_blocks)


async def in_session_blocks(
    session: AsyncSessionResource, query: str, *, turn_count: int = 0
) -> list[MemoryBlock]:
    """Fetch this session's blocks for the current turn, newest first.

    Two shapes, chosen by how long the conversation has run:

    - Up to `SEARCH_THRESHOLD_TURNS`, the whole session is fetched in order. The
      newest `VERBATIM_WINDOW_TURNS` exchanges are rendered in full and the rest
      compressed.
    - Past the threshold, fetching everything stops being reasonable, so recall
      becomes a semantic search against the shopper's message — with the newest
      exchanges still carried verbatim, because a follow-up like "the black one"
      refers to the turn just gone, which search has no reason to rank highly.
    """
    if turn_count < SEARCH_THRESHOLD_TURNS:
        return await _list_session_blocks(session)

    recent, found = await asyncio.gather(
        _recent_blocks(session, turns=VERBATIM_WINDOW_TURNS),
        session.search_memory(query=query),
    )

    # The window comes first so it wins the de-duplication and is what gets
    # rendered verbatim; the search results fill in behind it, compressed.
    ordered: list[MemoryBlock] = []
    seen: set[str] = set()
    for block in [*recent, *found.memory_blocks]:
        if block.block_id in seen:
            continue
        seen.add(block.block_id)
        ordered.append(block)

    return ordered


async def _search_all_sessions(
    session: AsyncSessionResource, query: str, *, block_type: str, relevant_k: int
) -> list[MemoryBlock]:
    """Search every session this shopper has, for one kind of block only.

    Filtering by annotation rather than sorting a mixed result is what gives each
    kind its own guaranteed allowance.
    """
    found = await session.search_memory(
        query=query,
        filters={
            "session_ids": "all",
            "annotations": {ANNOTATION_KEY: block_type},
            "relevant_k": relevant_k,
        },
    )
    return list(found.memory_blocks)


async def recall_across_sessions(
    session: AsyncSessionResource, query: str
) -> tuple[list[MemoryBlock], list[MemoryBlock]]:
    """Search the shopper's earlier visits, facts and turns separately.

    Returns `(facts, turns)` so the caller can admit them under their own
    budgets. Both searches are guarded individually: losing the turn search must
    not cost the fact search, since the facts are the durable half.
    """
    facts, turns = await asyncio.gather(
        _search_all_sessions(
            session, query, block_type=TYPE_FACT, relevant_k=CROSS_SESSION_FACT_K
        ),
        _search_all_sessions(
            session, query, block_type=TYPE_TURN, relevant_k=CROSS_SESSION_TURN_K
        ),
        return_exceptions=True,
    )

    if isinstance(facts, BaseException):
        logger.warning("Cross-session fact recall failed: %r", facts)
        facts = []
    if isinstance(turns, BaseException):
        logger.warning("Cross-session turn recall failed: %r", turns)
        turns = []

    return facts, turns


async def recall(
    session: AsyncSessionResource, query: str, *, turn_count: int = 0
) -> list[str]:
    """Recall everything worth giving the agent this turn.

    Three searches, issued together so the added latency is one round trip
    rather than three: the conversation in progress, the shopper's facts from
    every visit, and relevant exchanges from earlier visits.

    Each is guarded on its own. A shopper is better served by partial recall than
    by none, and the three fail for independent reasons.

    Earlier visits are rendered first and always compressed; the conversation in
    progress comes last, because that is what the shopper's message is replying
    to.
    """
    current, cross = await asyncio.gather(
        in_session_blocks(session, query, turn_count=turn_count),
        recall_across_sessions(session, query),
        return_exceptions=True,
    )

    if isinstance(current, BaseException):
        logger.warning("In-session recall failed: %r", current)
        current = []
    if isinstance(cross, BaseException):
        logger.warning("Cross-session recall failed: %r", cross)
        cross_facts, cross_turns = [], []
    else:
        cross_facts, cross_turns = cross

    # Searching "all" sessions includes the one in progress, so its blocks come
    # back twice. De-duplication is on block id and keeps the in-session copy,
    # which is the one whose verbatim window still applies — comparing rendered
    # text would not match, since the same block renders differently in the two
    # places.
    seen = {block.block_id for block in current}

    earlier: list[str] = []
    for block in [*cross_facts, *cross_turns]:
        if block.block_id in seen:
            continue
        seen.add(block.block_id)
        # Compressed always: earlier visits are background, not the exchange
        # being answered.
        line = render_block(block, verbatim=False)
        if line.strip():
            earlier.append(line)

    return [*earlier, *render_recalled(current, verbatim_turns=VERBATIM_WINDOW_TURNS)]


async def record_turn(
    session: AsyncSessionResource,
    query: str,
    answer: str,
    *,
    created_at: str | None = None,
) -> None:
    """Record a completed turn: always the exchange, sometimes a fact.

    The two are necessarily separate requests — the server rejects `messages`
    and `facts` in one call — and they are governed differently: the exchange
    decays on the session's retention, the fact does not expire at all.

    Processing is left to the server (`async_processing=True`) rather than
    waited out. A block comes back from both `list_memories` and `search_memory`
    while it is still `processing`, with its `message` fully populated and only
    `summary` and `contexts` empty — so the next turn can already recall it, and
    `render_turn()` falls to its raw-exchange rung until extraction lands. That
    is more prompt text for a turn or two, and the alternative was making the
    shopper wait out the extraction to be handed an answer already final.

    No `memory_block_ttl` is passed: the exchange inherits the retention of the
    session it belongs to. Passing one here would override the session default,
    which silently defeats a presenter who opened the session with a short
    retention — per-block TTL sits above session TTL in the hierarchy. The
    90-day default is applied once, where it belongs, at session creation.
    """
    await session.add_memory(
        messages=[ChatMessage(user_content=query, assistant_content=answer)],
        async_processing=True,
        annotations={ANNOTATION_KEY: TYPE_TURN},
        # Summaries and contexts are what compressed recall renders, so the
        # extraction must run; asked for explicitly rather than inherited from
        # the server's environment.
        context_required=True,
        created_at=created_at,
    )


async def record_facts(
    session: AsyncSessionResource,
    facts: list[str],
    *,
    created_at: str | None = None,
) -> None:
    """Store durable shopper facts, which never expire.

    `memory_block_ttl=0` is passed deliberately, to override whatever retention
    the session carries. That override is what lets a short-lived session still
    leave permanent facts behind — the divergence the retention demo turns on.

    Extraction is switched off: a fact is already an atomic statement, so the
    summary the server would generate only paraphrases it, and the block stays
    fully searchable without one.
    """
    if not facts:
        return

    await session.add_memory(
        facts=facts,
        async_processing=False,
        memory_block_ttl=FACT_BLOCK_TTL_SECONDS,
        annotations={ANNOTATION_KEY: TYPE_FACT},
        context_required=False,
        created_at=created_at,
    )
