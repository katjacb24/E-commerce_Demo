# AI Data Plane Agent Memory

What the Personal Assistant remembers, how long it keeps it, and how it is
recalled. Implemented in `backend/services/memory.py`, driven from
`backend/agents/user_agent.py`.

## Setup

Agent Memory runs as its **own container** alongside the app, storing blocks in
a separate `agent_memory` bucket on the same Capella cluster.

The backend talks to it via the `couchbase-agent-memory` Python SDK.

**Memory is an enhancement, not a dependency.** If the server is unavailable
the shopper still gets their answer, just without recall; every call sits behind
its own guard, and the write path is guarded separately from the read path.

## Which users get recorded memory

**Signed-in shoppers only** — a signed-out visitor gets a stateless assistant,
as there is no identity to file memories under. The chat panel shows which mode
is in force. The login is deliberately fake (`frontend/lib/auth.ts` —
client-side, plain-text, no session), purely so the assistant can answer as a
known shopper. 

**Sessions.** One conversation is one session. The frontend holds the session id
and passes it back every turn, so a new one is minted only when it arrives as
`None` — when the panel was opened, closed and reopened, or the shopper signed
in or out. **Closing and reopening the panel is how a "return visit" is
simulated.** Ids are `session{n}`, with `n` derived from the ids already stored
rather than their count, and must not contain `/` (they are interpolated into
`/users/{user_id}/sessions/{session_id}`).

## What is stored

| Kind | Written | Retention | Annotation |
|---|---|---|---|
| **Turn** — the question and the answer | every turn | 90 days (`MEMORY_MESSAGE_TTL_SECONDS`) | `type: turn` |
| **Fact** — something durable the shopper said about themselves | only when a turn contains one | never expires (`MEMORY_FACT_TTL_SECONDS=0`) | `type: fact` |

They are necessarily separate requests — the server rejects `messages` and
`facts` in one call.

- **Turns inherit the session's retention.** No per-block TTL is passed — it
  sits *above* session TTL.
- **Facts pass `memory_block_ttl=0`**, overriding the session's retention, so a
  short-lived session can still leave permanent facts behind.
- Turns are written with `context_required=True` (the server's summaries and
  contexts are what compressed recall renders); facts without it.
- **The `type` annotation is load-bearing.** Cross-session recall filters on it,
  exact-match, so a block written without one is unreachable. 

**How facts are identified.** An **LLM judge** runs *after* the answer, so it costs no
latency. It is prompted against a **closed category list** — clothing or shoe
size, preferred brand, colour preference or dislike, budget band, occasion —
since an open-ended prompt files conversational trivia as durable facts. Rules:
only what the *shopper* stated about themselves; a question is not a fact ("do
you have jeans under 50 EUR?" states no budget); one short third-person sentence
each. Its output is untrusted — `validate_facts()` discards anything that is not
a short non-blank string, de-duplicates, and caps at `MEMORY_MAX_FACTS_PER_TURN`.

`context_required=True/False` is what determines whether the LLM extraction of summaries 
and contexts happens - this is also what compressed recall renders. It is explicitly off 
for facts - record_facts() passes context_required=False, versus context_required=True in 
record_turn(). Reason: "a fact is already an atomic statement, so the summary the Agent
Memory server would generate only paraphrases it." So, fact blocks carry no summary/contexts. 

## What is recalled on a turn

Three searches/ calls, issued **concurrently** so the added latency is one round trip,
each guarded on its own — partial recall serves the shopper better than none,
and the three fail for independent reasons.

| | Scope | Filter | Budget | How it renders |
|---|---|---|---|---|
| 1 | The conversation in progress | this session only | `MEMORY_MAX_SESSION_BLOCKS` (200) | newest 3 exchanges as raw messages, everything older compressed |
| 2 | The shopper's facts, from every visit | `type: fact`, `session_ids: all` | `MEMORY_CROSS_SESSION_FACT_K` (10) | always raw fact |
| 3 | Turns from earlier visits | `type: turn`, `session_ids: all` | `MEMORY_CROSS_SESSION_TURN_K` (10) | always compressed |

2 and 3 are searched **separately** so each gets a guaranteed budget — a chatty
past session cannot crowd out a stored preference. Searching "all" sessions
includes the one in progress, so its blocks return twice; de-duplication is on
**block id**, keeping search 1's copy, which is the one whose verbatim window
still applies.

### Search 1: two shapes, chosen by conversation length

`turn_count` is how many exchanges the session has had, sent by the frontend —
not a count of blocks, so stored facts never push it along.

- **Under `MEMORY_SEARCH_THRESHOLD_TURNS` (10):** the whole session is listed in
  order, no search involved. Listing pages past the server's 20-per-page default
  and stops at `MEMORY_MAX_SESSION_BLOCKS` (200).
- **At or past it:** listing everything stops being reasonable, so it becomes a
  semantic search against the shopper's message, *plus* a listing of enough of
  the newest blocks to cover `MEMORY_VERBATIM_WINDOW_TURNS` (3) exchanges. That
  window is fetched first so it wins de-duplication and keeps its verbatim
  rendering, with search results filling in behind it; it is carried whatever
  its score, because a follow-up refers to the turn just gone, which search
  would not rank highly.

Either way the blocks come back mixed: **facts stored earlier in this session
are listed alongside its exchanges**, and render as facts. list_memories is 
unfiltered, so facts written earlier in this session come back in the same listing 
and render as facts. _recent_blocks even over-requests (turns * 3 + 3 blocks) 
specifically to leave room for them.

### How an exchange renders: verbatim or compressed

The two thresholds `MEMORY_VERBATIM_WINDOW_TURNS` (3) and `MEMORY_SEARCH_THRESHOLD_TURNS` (10)
are independent of each other and determine 2 different things. 

`MEMORY_SEARCH_THRESHOLD_TURNS` (10) never decides whether messages are rendered 
as raw messages vs. compressed (as contexts -> summary -> raw messages). It only 
decides: list everything vs. semantic search + newest window. E.g. Under the 
threshold, a 9-turn session is fetched whole, but render_recalled() still renders 
only the newest 3 in full (as raw messages), whereas the turns 1–6 arrive compressed.
Facts are not counted towards the thresholf of `MEMORY_SEARCH_THRESHOLD_TURNS` (10), 
as turn_count is a request field the frontend increments per exchange (assistant.py:112), 
not a memory block count, so only message turns are counted here. 

The newest `MEMORY_VERBATIM_WINDOW_TURNS` (3) exchanges go to the agent **in
full**; every older exchange gets compressed. That window of exchanges is what lets 
*"the black one, do you have it in M?"* be answered correctly. Facts are not counted
towards the threshold of `MEMORY_VERBATIM_WINDOW_TURNS` (3) as turns_seen increments 
only if block.message and not block.fact, so only message turns are counted here.

So, **`MEMORY_SEARCH_THRESHOLD_TURNS` (10)** decides *which* blocks Search 1
returns, whereas **`MEMORY_VERBATIM_WINDOW_TURNS` (3)** decides *how* each returned 
exchange is written into the prompt.

Compressing one exchange takes the **first of these that is non-empty**: the
server's extracted `contexts`, its generated `summary`, or the raw exchange. The
last is a safety net — a block whose extraction failed comes back from search
with both fields empty, and must not contribute a blank line to the prompt.

A **fact** never goes through any of this. Whichever search returned it, it
renders whole, with the date it was stated.

Earlier visits render first and always compressed; the conversation in progress
comes last, because that is what the shopper's message is replying to.

## How recalled memory reaches the agent

Recalled memories ride on the **system prompt**, not the message list — they are
background, not a turn to answer. The suffix (`memory_context()`) imposes four
rules:

- **Never tell the customer** memories are being consulted, and never repeat one
  back as new information.
- **Resolve contradictions by recency.** Recalled facts carry the date they were
  stated; act on the most recent and disregard the older without asking. (The
  Agent memory server stores the timestamps but does not act on them). A fact's date comes from `created_at` (the shopper's own timeline, which a dated session sets), falling back to `ingested_at`.
- **Memories are leads, not results.** A product named months ago may have
  changed price or sizes, or been withdrawn — look it up with a tool first, and
  take price, SKU and sizes only from the tool's response.
- **Never link a product whose SKU came from a memory**, or it will invent one
  from a remembered name.

## Demo-only presenter controls

The chat panel's **🎛 Demo controls** strip carries a **session date** and a
**message retention** setting, so cross-visit recall and retention can be shown
live. Retention presets: *Default (90 days)*, *1 minute*, *5 minutes*,
*1 hour*, *Never expire*.

Both describe the **session**, not the turn, so both must be set **before the
first message** in the current chat and lock once it starts; after locking the control shows what the session is actually running with, read back off the session. 
Closing the panel ends the session and clears both. A dated session takes the 
**day** from the control and the **time of day** from the real clock, so turns stay in chronological order; a malformed date is rejected with a `422`.

> **Session dating does not backdate TTL expiry.** Couchbase computes expiry from
> write time, so a session dated six months ago still holds messages a full
> retention period from expiring. Use the retention control for expiry stories.

## Out of scope

Memory for signed-out visitors · memory for the admin agent · editing or
deleting a fact from the UI (contradictions are resolved by recency instead —
both facts stay stored, which is the point) · cross-user memory · OIDC auth on
the memory server (`OIDC_AUTH_ENABLED=false`) · production retention/consent policy.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Retention control greyed out | a message was already sent; retention is fixed at session creation. Reopen the panel. |
| A returning shopper remembers nothing | no earlier visit exists |
| A dated session's messages did not expire | dating does not backdate expiry |
| Answers arrive but nothing is recalled | the Agent Memory server is down (`curl http://localhost:8080/health`) |
| Nothing written while signed out | by design |