## Context

See [proposal.md](proposal.md) — Why. This section records only what was established empirically about the Couchbase Agent Memory server, because several design decisions below turn on behaviour the documentation does not state.

Findings from the running server (v1.0.0) and the `agent_memory` bucket underneath it:

- **`messages` and `facts` cannot share one request.** The SDK raises `ValidationError: "messages and facts cannot be provided together; submit them as separate requests"`. Two calls is not a style choice.
- **TTL is in seconds and follows a three-level hierarchy**, most specific winning: server env `AGENTMEMORY_MEMORY_BLOCK_TTL` < `create_session(memory_blocks_ttl=...)` < `add_memory(memory_block_ttl=...)`.
- **The server does not resolve contradictions.** The documentation's wording is *"When an **agent** retrieves contradictory memories, **it** uses the timestamp on each memory block."* Nothing deduplicates or supersedes. Search ranks by semantic relevance (`rel_score`), and two contradictory statements of the same preference have near-identical embeddings, so both return, adjacent.
- **`summary` and `contexts` are twin outputs of one extraction step**, populated together and null together. `contexts` is a list of atomic assertions; `summary` is one prose sentence.
- **Retrieval does not use either of them.** Each block carries a single 2048-dim embedding regardless of how many contexts it has, and a block with `status: extraction_failed` still has a full embedding, no summary, and no contexts — and still ranks in search results. Vector-cosine probing against the raw exchange scores higher than against the summary. So `summary`/`contexts` are a read-side rendering choice only.
- **`context_required` switches extraction on and off; it is not a strictness flag.** Established by spike (task 1.2): with `context_required=False` a block is stored `ready` with `summary` and `contexts` both `null` — extraction simply does not run. With `True` it runs. It does **not** mean "reject the block if extraction fails", which is what this design originally assumed. Passing it explicitly removes the dependency on the server's `AGENTMEMORY_*` default.
- **Skipping extraction does not cost searchability.** A block written with `context_required=False` is still embedded and still ranks: in the spike, a fact stored with extraction off ranked top (0.771) for a semantic query it matched. Confirms that embedding and extraction are independent paths.
- **Facts gain nothing from extraction.** For the fact `"The shopper's usual size is M."` the generated `summary` was `"The shopper's usual clothing size is M."` and `contexts` was `["The shopper's usual size is M."]` — a paraphrase and a verbatim copy of content that is already atomic.
- **Extraction fails in practice.** At the time of this survey one of the five blocks stored was `extraction_failed`, and it returned ranked #2 in a live search. The server's extraction model is `mistralai/mistral-7b-instruct-v0.3`.
- **`FilterOptions`** offers `session_ids` (list, or `"all"`), `relevant_k` (default 10), `annotations`, `order_by`, and created/ingested time bounds. Search has no context-related parameter.
- **Annotation filtering is honoured and is exact-match.** Verified against the running server: an unfiltered cross-session search returns all 5 stored blocks; the same search with `annotations={"type": "turn"}` returns 0, because no existing block carries annotations. Annotation values are `str` only — no ranges. Annotations passed to `add_memory` apply to every block in that call.
- **`add_memory(created_at=...)`** accepts a backdated ISO 8601 timestamp, validated with `datetime.fromisoformat`. The API documents it as "stored as null if not provided", but every block currently in the store has `created_at` populated and equal to `ingested_at`, so the server or SDK defaults it. Renderers should still be defensive and fall back to `ingested_at`.
- **`created_at` is a first-class filter and sort dimension**, distinct from `ingested_at`: `FilterOptions` exposes `created_start_time` / `created_end_time` alongside `start_time` / `end_time`, and `order_by` accepts either. Its default is `ingested_at`.

Today all of this lives in [backend/agents/user_agent.py](backend/agents/user_agent.py): `MEMORY_BLOCK_TTL = 0`, `_ensure_session`, `_format_memories`, `_memory_context`, and an inline recall → answer → write sequence in `run_agent`.

## Goals / Non-Goals

**Goals:**

- Keep the agent node itself unaware of memory. Recall stays a system-prompt suffix; the agent contract does not change.
- Add no latency to first token. Every added cost lands after the answer is produced, or runs concurrently with work already happening.
- Degrade in layers: cross-session recall failing must not take in-session recall with it, and neither must take the answer.
- Make retention and cross-visit recall demonstrable inside a live demo, not only over 90 real days.

**Non-Goals:**

- Annotations beyond `type`, supersede-on-write conflict resolution, and changing the server's extraction model — all deferred (see proposal, *Explicitly out of scope*). The `type` annotation is in scope and load-bearing (decision 6).
- Reconstructing full conversation history for the agent's message list. Memory remains the only mechanism carrying context between turns; the agent is still invoked with a single user query.
- Any change to signed-out behaviour.

## Decisions

### 1. Extract memory handling out of `user_agent.py` into its own module

`run_agent` currently interleaves identity, session, recall, answer, and write. This change roughly triples the recall logic and adds a second LLM call. Keeping it inline makes the graph node hard to read and the memory policy impossible to test on its own.

A `backend/agents/memory.py` (or `backend/services/memory.py`, matching the existing `services/` convention) owns: session lifecycle, the two recalls, rendering, and the fact judge. `run_agent` calls into it and stays a readable sequence.

*Alternative considered:* leave it inline. Rejected — the fact judge alone wants isolated tests, and mocking the whole agent graph to test a rendering rule is disproportionate.

### 2. Sliding window over the three-tier ladder

The recall shape is: **last N turns verbatim, older turns compressed, and past a threshold switch from "fetch everything" to semantic search.** Proposed starting values `N = 3`, threshold `= 10`, to be tuned against the demo script.

The rejected alternative was a global switch to summaries at turn 3. The failure mode is concrete: at turn 4 a shopper says *"the black one, do you have it in M?"*, and the summary of turn 3 reads *"the assistant provided a list of jeans under 50 EUR"* — the black one is gone. Compression is right for old turns and wrong for the immediately preceding one, so the boundary should be recency, not conversation length.

### 3. `list_memories` for the window, `search_memory` past the threshold

Under the threshold the intent is "give me this conversation in order", which is what `list_memories(session_ids=None, limit, offset, order_by)` expresses. A query-less `search_memory` would also work — `query` is optional — but returns no meaningful ordering. Note `list_memories` defaults to `limit=20`, max 200.

Above the threshold, `search_memory(query=user_query)` with the default session scope.

### 4. Turn count comes from session state, not a round trip

Choosing between window and search needs the conversation's turn count. `list_memories` returns `total`, but calling it just to count costs a round trip on every turn. The `session_id` already round-trips through the frontend on each request; the turn count rides along with it. Session `metadata` is the fallback if the frontend cannot be changed.

*Trade-off:* a client-supplied count is spoofable. The consequence of a wrong count is a differently-shaped prompt, not a data leak — memory access is still gated on server-side identity — so this is acceptable.

### 5. Three concurrent recalls, deduplicated on `block_id`

In-session recall and the two cross-session recalls (decision 6) are independent, each costing an embedding round trip. All three are issued together with `asyncio.gather` so the added latency is one round trip, not three. Each is individually guarded so one failing does not lose the others — in particular, losing the turn search must not lose the fact search.

`session_ids="all"` includes the session in progress, so its results overlap the in-session recall. Deduplication is on `block_id`, keeping the in-session copy.

*Alternative considered:* pass the explicit list of *other* session ids from `user.sessions`. Rejected — it grows with visit count and still needs the dedupe path for safety.

### 6. Facts and turns are annotated on write and retrieved as separate filtered searches

Every block carries a `type` annotation: `add_memory(messages=[...], annotations={"type": "turn"})` and `add_memory(facts=[...], annotations={"type": "fact"})`. Annotations apply to every block in a call, and the two kinds are already separate calls (see Context), so this costs nothing extra on the write path.

Cross-session recall is then two filtered searches rather than one broad one:

```
  FilterOptions(session_ids="all", annotations={"type": "fact"}, relevant_k=<fact budget>)
  FilterOptions(session_ids="all", annotations={"type": "turn"}, relevant_k=<turn budget>)
```

Each kind gets its own guaranteed budget, so a chatty past session cannot crowd out a stored preference — the failure mode is structurally impossible rather than mitigated after the fact. It also lets the budgets be tuned independently: facts are short and high-value, so a small `relevant_k` goes a long way; turns are long, so theirs is the one to keep tight.

*Alternative considered:* one unfiltered search with a raised `relevant_k` and a client-side partition on whether the returned block has `fact` or `message` populated. This was the original design when annotations were deferred. It works, but it only makes crowding *unlikely* — a shopper with a long history can still push every fact below the cut — and it spends tokens retrieving blocks it then discards.

*Consequence:* this makes annotations load-bearing rather than decorative. A block written without the `type` annotation is invisible to cross-session recall. That applies to every block already in the store — see Migration Plan.

### 7. Rendering ladder: `contexts` → `summary` → raw message, and facts render as themselves

A fact block renders from its `fact` field directly. Extraction adds nothing to an already-atomic statement (see Context), and the paraphrase it produces can drift from what the shopper actually said — so facts skip the ladder entirely.

The ladder below therefore applies to message blocks. For compressed rendering, prefer `contexts` over `summary`, and **keep every context line**.

Filtering the context lines was tried and reverted (task 6.2). The heuristic — keep attributed statements, drop generic restatements — looked sound against the example that motivated it (`Jeans are priced in EUR`). Against a real stored block it failed badly:

```
  1. "User requested jeans under 70 EUR"                                  kept
  2. "The assistant provided a list of jeans available for under 70 EUR"   dropped
  3. "The list includes Men's Light Blue Slim Jeans, Men's Medium-Wash
      Slim Jeans, Men's Dark Blue Denim Jeans, and more."                  dropped
```

Line 3 is the only one naming actual products, and it reads as generic prose to any cheap heuristic. Dropping it destroys exactly the referent that makes a later "the black one" resolvable — the same failure that made compression recency-based rather than length-based in the first place. Extraction is already the compression step; a second filter over it is speculative, and the few tokens it saves are worth far less than a lost product list. Both come from the same extraction and cost the same, but `contexts` is a list of atomic assertions where `summary` is a single prose sentence, so `contexts` keeps the specifics — the named products, the stated constraint — that summarising into one sentence flattens away. It also matches the existing bullet rendering in `_memory_context`.

Raw message is the last rung and is **not optional**: `extraction_failed` blocks are fully searchable with both fields null, and today they are one block in five. A renderer that stops at `summary` emits blank lines into the prompt.

### 8. Contradiction handling is a prompt contract

Fact lines are rendered with their `created_at`, and the system prompt instructs the agent to prefer the most recent when facts conflict. This requires `_format_memories` to stop discarding timestamps, which it does today.

*Alternatives considered:* `order_by="created_at"` — interacts with relevance ranking in ways not established, and ordering alone does not tell the agent which to believe. Supersede-on-write — stronger, and explicitly deferred.

*Known weakness:* this depends on the agent noticing the conflict. It is the documented mechanism, and it is cheap; it is not robust. Worth a task to verify on a scripted pink→blue exchange.

### 9. Fact judging is a dedicated LLM call, after the answer

A second call, prompted to return zero or more durable shopper facts, issued after the answer is returned so first-token latency is untouched. Facts are written with `add_memory(facts=[...], memory_block_ttl=0)`, overriding the session's 90-day default.

**Extraction is switched off for fact writes** (`context_required=False`) and explicitly on for message writes (`context_required=True`). Facts do not benefit from it (decision 7) and skipping it saves one server-side LLM call per fact, while the block stays fully searchable (see Context). Setting it explicitly on both paths also means the app no longer depends on how the server's environment happens to be configured.

*Alternative considered:* reuse the `contexts` the server already extracts. Genuinely attractive — the decomposition is free and already stored — but contexts are conversation-scoped, not durable facts (*"Jeans are priced in EUR"* is not a fact about the shopper), and reading them back needs a follow-up fetch because `AddMemoryResponse` returns only `block_ids`. Deferred, not dismissed.

The judge's output must be constrained (a short list of strings, or empty) and validated before writing, so a chatty model cannot fill the store with pseudo-facts.

### 10. TTL: session default 90 days, facts override to 0

`create_session(memory_blocks_ttl=7_776_000)` sets the message default; the facts call passes `memory_block_ttl=0`. `MEMORY_BLOCK_TTL = 0` at [user_agent.py:88](backend/agents/user_agent.py#L88) is replaced by two named constants.

Both belong in configuration rather than as literals, because the demo needs to shorten them (see below).

### 11. Session dating is a per-session `created_at` override

The chat panel offers a date input. The chosen date is carried with the request alongside `session_id` and the turn count, and the backend combines it with the current clock time to build the `created_at` passed to both the message write and the fact write for every turn in that session. Nothing else is altered: `ingested_at`, TTL, annotations and processing all behave normally.

Taking the time of day from the real clock rather than fixing it means turns within a dated session stay monotonically ordered, so a dated conversation reads correctly if anything ever sorts by `created_at`.

The override applies to **facts as well as messages**, and that is the point. Decision 8 resolves contradictions by presenting each fact's `created_at` and asking the agent to prefer the newest. Demonstrating that needs two facts with meaningfully different dates, which otherwise means waiting months. Session dating is what makes the pink→blue scenario performable live.

**The control locks once the conversation has started, and clears when it ends.** Unlike retention, nothing in the server forces this — `created_at` is passed on every write, so a mid-conversation change would be honoured. That is exactly why the UI forbids it: a session whose early turns are dated March and whose later ones are dated today is not a thing the demo ever wants to show, and it would quietly corrupt the contradiction scenario of decision 8, which reads the newest fact. Locking makes the control mean *this session happened on this date*. Both presenter controls clear when the panel closes, for the same reason the conversation does: a date carried over into the next session would silently backdate it, which is the harder mistake to notice.

**Not gated.** This application exists to be demonstrated, so the control is a permanent part of it rather than something hidden behind a flag. Worth stating plainly for anyone reading this as a production pattern: a client choosing a stored timestamp is a client writing to a trusted field, and in a real shop this control would not exist.

*Alternative considered:* a pre-seeded history script, run before the demo. Still worth having for bulk history (task 7.1), but it cannot show the *creation* of a past conversation, which is the part that makes the mechanism legible to an audience. The two complement each other.

*Alternative considered:* faking the clock server-side for the whole process. Rejected — it would backdate `ingested_at` and TTL as well, making the demo state diverge from anything real, and it cannot vary per session.

### 12. Session dating and TTL demonstration are separate levers

Couchbase computes document expiry as an absolute time at write, so a backdated `created_at` does not backdate expiry: a session dated six months ago still holds messages that are 90 days from expiring. This must not be conflated in the demo narrative — *"the old messages have expired, only the facts survive"* will not be true of a dated session.

The two stories therefore use different mechanisms:

```
  "you remembered me from months ago"  -> session dating (created_at)
  "old chat decays, facts persist"     -> user.modify_ttl() on a live session
```

Both are in scope; conflating them produces a demo that quietly contradicts itself.

**Verified** (task 7.1). A block written with `created_at` 180 days in the past and `memory_block_ttl=3600` stored `meta().expiration` 3605 seconds after its `ingested_at` — the TTL counted from write time, with `created_at` ignored. Had expiry followed `created_at`, the block would have been born already expired.

### 13. Retention is chosen at session creation, and the constraint is surfaced rather than worked around

`memory_blocks_ttl` is an argument to `create_session`, and `_ensure_session` creates the session lazily — on the first turn, when `session_id` arrives as `None`. So a retention value is only actionable on that first request; on any later turn the session already exists and the value has nowhere to go.

Rather than hide this, the design surfaces it: the control is editable until the first message is sent and then locks, showing the retention the session was opened with. A presenter who needs a different value opens a new session, which the panel already does on close and reopen.

Both controls lock on the same signal — the shopper having sent a message — rather than on the session id coming back, so the lock lands when the value stops being actionable rather than one round trip later. Retention has already gone out with that request; the date, per decision 11, is locked by choice.

**Why this demonstrates the TTL hierarchy well.** The session's retention becomes the default for its message blocks, and the fact write passes `memory_block_ttl=0` (decision 10), which overrides it. So a one-minute session retention produces exactly the divergence worth showing:

```
  session retention = 60s
        |
        +-- message blocks  -> inherit 60s   -> gone after a minute
        |
        +-- fact blocks     -> override to 0 -> persist
```

After the minute, cross-session recall for that shopper returns their stated preferences and none of the conversation that produced them. That is the whole retention argument in one observable step.

*Alternative considered:* allow mid-session retention changes via `user.modify_ttl(new_ttl, session_id=...)`, which does re-stamp existing blocks. Rejected for the default path: `modify_ttl` scoped to a session hits **every** block in it, facts included, which destroys the very divergence the demo exists to show. It only works if the call passes the explicit `block_ids` of message blocks alone — extra machinery for a case a new session already covers. It remains the right tool for retro-expiring a session that was opened at the default (task 7.6), where facts are not yet involved.

*Trade-off:* a client choosing retention is the same class of concern as a client choosing `created_at`, and is accepted for the same reason.

**Caveat for the demo script:** if the conversation runs longer than the retention set for it, its earliest turns expire while it is still in progress, and the sliding window silently gets shorter. This is faithful behaviour and can even be shown deliberately, but a retention chosen for a short conversation should comfortably outlast it.

### 14. Recalled memories are presented as leads, not results

Found while writing the demo script. Cross-session turns render compressed, and
compression drops URLs — so a product named in a recalled conversation reaches the
agent with no SKU behind it. The agent treated those names as though they had come
from a tool call and **invented plausible SKUs** (`BLOUSE-GNG-BLU-001` for the real
`BLSE-SLS-GNG-001`), producing broken links, in direct violation of the base
prompt's "never invent a link".

Reordering or un-compressing the seeded content does not fix it; the agent will
trust any product name it is handed. So the memory prompt now states that these
are records of past conversations rather than catalogue data, that a product in
them may have changed price or been withdrawn, and that any product mentioned must
be looked up before it is named — price, sku and sizes taken only from the tool
result.

This is correctness, not just link hygiene: a remembered price is stale by
construction, and quoting one back is worse than not remembering it.

## Risks / Trade-offs

- **A 90-day retention is invisible on stage** → The retention control (decision 13) lets a session be opened with seconds of retention, and `user.modify_ttl()` retro-expires a session already open. Watching recall go quiet after a minute demonstrates retention; waiting 90 days does not.
- **Cross-session recall has nothing to find on a fresh demo cluster** → Session dating (decision 11) creates the past live; the seeding script covers bulk history. Highest-leverage pair for demo quality.
- **Neither presenter control belongs in a production shop** → Accepted: this application is a demo. Recorded here so the decision is deliberate rather than an oversight, and noted in the README.
- **A presenter sets retention after the first message and believes it applied** → The control locks once the session exists and displays the retention actually in force, read back from the session's `blocks_ttl`. Verified by a test.
- **`ingested_at` betraying the illusion** → A dated session's blocks carry a months-old `created_at` and today's `ingested_at`. Anything rendered to the agent or shown in the UI must read `created_at`; task 6.3 already requires this, and it is the field the contradiction prompt depends on.
- **Conflating session dating with expiry** → Decision 12. The demo script must keep the two narratives apart.
- **~20% extraction failure rate** → The rendering ladder (decision 7) makes this survivable rather than visible. Not fixed here; if the rate proves worse under demo load, pointing `AGENTMEMORY_LLM_MODEL` at a stronger Capella-hosted model is a one-line env change and a separate concern.
- **Facts crowded out of cross-session results** → Structurally prevented by the separate filtered searches in decision 6. Residual risk is only that a shopper accumulates more facts than the fact budget holds; recency ordering within that search bounds it.
- **A block stuck in the server's extraction retry queue cannot be annotated at all** → Found during the backfill (task 5.1): `update_memory` on the `extraction_failed` block returns `500 "Memory block is currently being processed"`. The backfill reports such blocks and continues rather than aborting, but they stay invisible to filtered cross-session recall until the server settles and the backfill is re-run. One block of eight was in this state when the backfill ran. Residual and accepted: it is a single stale demo block, and the alternative — deleting and rewriting it — destroys content to fix an annotation.
- **A block written without the `type` annotation is unreachable by cross-session recall** → Annotations are now load-bearing. Every write path must set `type`, and the backfill in the Migration Plan must run before the new recall ships. Worth a test that asserts no write path omits the annotation.
- **The agent ignores the conflict instruction** → Decision 8's known weakness. Bounded by verifying against a scripted contradiction; escalation path is supersede-on-write in a later change.
- **The fact judge writes noise** → Constrain and validate its output; keep the fact category list closed (size, brand, colour, budget band, occasion) rather than open-ended.
- **Two recalls plus a judge call per turn raises cost per conversation** → Recalls are concurrent and the judge runs off the answer path, so the shopper-visible cost is one extra round trip. Token cost per turn rises; acceptable for a demo, worth noting for anyone reading this as a production pattern.
- **Blocks are only searchable once `ready`** → The existing `async_processing=False` on the message write already handles this and must be kept on the fact write too, or a fact stated in one turn will not be recallable in the next.

## Migration Plan

**Retention:** no migration. Existing blocks were written with TTL 0 and keep it; the new 90-day default applies to blocks written after this change.

**Annotations:** a backfill is required, implemented as `backend/scripts/backfill_memory_annotations.py` (idempotent, with `--dry-run`). Every block currently in the store has empty annotations, and annotation filtering is exact-match, so those blocks match neither `type: fact` nor `type: turn` and would silently vanish from cross-session recall. All existing blocks are messages, so the backfill is a single pass calling `update_memory(block_id, annotations={"type": "turn"})` over them. Supplying only `annotations` does not regenerate embeddings or summaries, so this is cheap and non-destructive. The store held five blocks when this was written, so this is a script, not a migration framework.

The backfill must run before, or together with, the code that starts filtering — the ordering matters, since filtered recall against un-backfilled data looks like working code that remembers nothing.

**Rollback:** reverting the code is sufficient. Backfilled annotations are inert to the current implementation, which does not filter on them, so the store stays readable either way.

## Open Questions

<!-- Answered during implementation: fact blocks DO receive summary and contexts, but
     both are redundant for atomic content (decision 7); and `context_required` toggles
     whether extraction runs rather than enforcing that it succeed (decision 9). Both are
     recorded in Context above. -->

None outstanding. The verbatim window and search threshold settled at their proposed values — N=3, threshold=10 — which held up against the demo script in the end-to-end scenarios (tasks 8.1–8.4). Both remain configurable (task 1.4), so retuning does not need a design change.
