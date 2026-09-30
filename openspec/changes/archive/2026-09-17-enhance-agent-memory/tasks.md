## 1. Spikes and configuration groundwork

- [x] 1.1 Write one throwaway fact block to a scratch user and inspect it, to answer design.md Open Question 1 (do fact blocks carry `summary`/`contexts`?); record the answer in design.md and delete the scratch user
- [x] 1.2 Write one block with `context_required=True` against a deliberately unextractable input to answer Open Question 2 (reject vs store degraded); record the answer in design.md and delete the scratch data
- [x] 1.3 Replace `MEMORY_BLOCK_TTL` in [backend/agents/user_agent.py](backend/agents/user_agent.py) with configurable `MESSAGE_BLOCK_TTL_SECONDS` (default 7_776_000) and `FACT_BLOCK_TTL_SECONDS` (default 0), both readable from `backend/.env`; verify both resolve to their defaults with no env override and to overridden values when set
- [x] 1.4 Add configuration for the verbatim window size (default 3) and the search threshold (default 10); verify they are read once at import and surfaced in the module's public constants

## 2. Extract the memory module

- [x] 2.1 Create the memory module (`backend/services/memory.py`, matching the existing `services/` convention) and move `_ensure_user`, `_ensure_session`, `_new_session_id`, `_format_memories` and `_memory_context` into it unchanged; verify `pytest` passes and the assistant still answers end to end with recall working exactly as before
- [x] 2.2 Move the recall-and-write sequence out of `run_agent` into a pair of module functions (recall for a turn, record for a turn), leaving `run_agent` as a readable sequence; verify `pytest` passes and behaviour is unchanged
- [x] 2.3 Add a test module for memory with the Agent Memory client mocked, following the mocking style in [backend/tests/test_products_api.py](backend/tests/test_products_api.py); verify the new tests run without a live memory server

## 3. Write path — retention and facts

- [x] 3.1 Pass `memory_blocks_ttl=MESSAGE_BLOCK_TTL_SECONDS` to `create_session`; verify a newly created session reports the 90-day `blocks_ttl` when fetched back
- [x] 3.2 Implement the fact judge: an LLM call issued after the answer is produced, prompted against a closed category list (size, brand, colour, budget band, occasion), returning zero or more short fact strings; verify unit tests cover a turn with a fact, a turn without, and a malformed model response
- [x] 3.3 Validate and bound the judge's output before writing (list of non-blank strings, capped count and length); verify a test feeding it prose or an oversized list results in no write
- [x] 3.4 Write accepted facts with `add_memory(facts=[...], memory_block_ttl=FACT_BLOCK_TTL_SECONDS, async_processing=False)` as a separate call from the message write; verify a test asserts two distinct calls and that facts are never passed alongside messages
- [x] 3.5 Annotate every write with its kind — `annotations={"type": "turn"}` on the message write, `annotations={"type": "fact"}` on the fact write; verify a test asserts the annotation on both calls and that no write path can omit it
- [x] 3.6 Guard the judge and the fact write so failure in either still records the message memory and still returns the answer; verify tests covering judge failure and fact-write failure

## 4. Read path — in-session recall

- [x] 4.1 Thread a turn counter alongside `session_id` through the assistant request/response path ([backend/routers/assistant.py](backend/routers/assistant.py), [frontend/lib/assistant.ts](frontend/lib/assistant.ts), [frontend/components/ChatbotPanel.tsx](frontend/components/ChatbotPanel.tsx)); verify the count increments across turns and resets when the panel is closed and reopened
- [x] 4.2 Implement the sliding window: below the search threshold, fetch the session with `list_memories`, render the most recent N turns verbatim and older turns compressed; verify unit tests at 1, 3, 4 and 9 turns assert which turns render raw and which render compressed
- [x] 4.3 Implement the search tier: at or above the threshold, use `search_memory(query=user_query)` at session scope while keeping the most recent N turns verbatim; verify a unit test at 11 turns asserts both the search call and the retained verbatim window
- [x] 4.4 Handle the `list_memories` default limit of 20 (max 200) so a long session is not silently truncated; verify a test with more turns than the default limit

## 5. Read path — cross-session recall

- [x] 5.1 Write and run the annotation backfill: `update_memory(block_id, annotations={"type": "turn"})` over every existing block, supplying only annotations so embeddings and summaries are not regenerated; verify a cross-session search filtered on `type: turn` returns the previously invisible blocks (currently 0 of 5)
- [x] 5.2 Add cross-session fact recall using `FilterOptions(session_ids="all", annotations={"type": "fact"}, relevant_k=<fact budget>)`; verify a test asserts the filter shape sent to the client
- [x] 5.3 Add cross-session turn recall using `FilterOptions(session_ids="all", annotations={"type": "turn"}, relevant_k=<turn budget>)`, rendering compressed only; verify a test asserts the filter shape and that only compressed text is rendered
- [x] 5.4 Make the two budgets independently configurable and verify a test where the turn search returns its full budget still admits every fact the fact search returned
- [x] 5.5 Deduplicate cross-session results against in-session results on `block_id`, keeping the in-session copy; verify a test with a deliberately overlapping block asserts it renders once
- [x] 5.6 Issue all three recalls concurrently with `asyncio.gather` and guard them independently; verify tests where each recall fails in turn assert the others' results still reach the prompt and the answer is still produced — in particular that losing the turn search does not lose the fact search

## 6. Rendering

- [x] 6.1 Implement the rendering ladder `contexts` → `summary` → raw message in `_format_memories`; verify tests for a block with contexts, a block with only a summary, and an `extraction_failed` block with neither, asserting none produce empty output
- [x] 6.2 Render every `contexts` line rather than filtering them — filtering was implemented, shown to discard the only line naming products, and reverted (see design.md decision 7); verify a test using the real context list from a stored block asserts every item survives
- [x] 6.3 Render each fact with its `created_at` timestamp, which `_format_memories` currently discards, falling back to `ingested_at` when `created_at` is absent; verify tests assert the timestamp appears in the rendered line and that a block without `created_at` still renders a time
- [x] 6.4 Extend the system prompt in `_memory_context` to instruct the agent to prefer the most recent fact on conflict, while keeping the existing "never mention memories" instruction; verify the rendered prompt in a test snapshot
- [x] 6.5 Extend the same prompt to state that recalled memories are records of past conversations rather than catalogue data, and that any product named in one must be looked up with a tool before it is named — price, sku and sizes taken only from the tool result (design.md decision 14); verify a test asserts the instruction is present and that a product recalled from a seeded session is never linked from a memory-derived sku

## 7. Presenter controls and demo enablement

- [x] 7.1 Verify the expiry-clock assumption behind design.md decision 12: write one block with a backdated `created_at` and a short TTL, read `meta().expiration` for it, and confirm expiry is counted from write time not from `created_at`; record the result in design.md and delete the scratch block
- [x] 7.2 Accept an optional session date on the assistant endpoint ([backend/routers/assistant.py](backend/routers/assistant.py)), combining it with the current clock time into a `created_at`; verify tests covering a valid date and a malformed date
- [x] 7.3 Pass the resulting `created_at` to both the message write and the fact write for every turn in the session; verify a test asserts the same `created_at` reaches both calls and that `ingested_at`, retention and annotations are unaffected
- [x] 7.4 Accept an optional retention value on the assistant endpoint, applied as `create_session(memory_blocks_ttl=...)` only on the request that creates the session and ignored on later turns; verify tests covering a value on the first turn, a value on a later turn (which must not change the session), and no value (which must yield the 90-day default)
- [x] 7.5 Return the session's retention actually in force (from the session's `blocks_ttl`) with the assistant response so the panel can display it; verify a test asserts the returned value matches what the session was created with
- [x] 7.6 Add both presenter controls to [frontend/components/ChatbotPanel.tsx](frontend/components/ChatbotPanel.tsx), carrying their values through [frontend/lib/assistant.ts](frontend/lib/assistant.ts), with **both** controls editable only until the first message of the session is sent and then locked — retention showing the retention in force, the session date showing the date the conversation is running under; verify the lock behaviour for each, that both values persist across turns of one session, and that both controls clear when the panel is closed and reopened so the next session starts undated and at the default retention
- [x] 7.7 Add a seeding script that writes bulk backdated memories with `add_memory(created_at=<ISO timestamp months ago>)` for the demo shopper, for history too voluminous to create live; verify the seeded blocks come back from a cross-session search
- [x] 7.8 Document retro-expiring an already-open session with `user.modify_ttl(new_ttl, session_id=...)` in [Part B of the README](../../../../README.md#part-b--agent-memory), noting that scoping it to a session also re-stamps fact blocks unless explicit `block_ids` are passed, and that session dating does not backdate expiry; verify by shortening a session's retention and observing recall go quiet
- [x] 7.9 Update [README.md](README.md) with the memory model — what is stored, retention per type, what is recalled per turn, and that both presenter controls exist for demonstration and would not belong in a production shop; verify the described behaviour matches the implementation

## 8. End-to-end verification

- [x] 8.1 Verify the pink→blue contradiction scenario end to end using the demo date control: date a session months back and state a preference, open an undated session and state a contradicting one, confirm the agent acts on the newer fact (design.md decision 8's known weakness)
- [x] 8.2 Verify the follow-up referent scenario: ask for products, then "the black one, do you have it in M?" at turn 4, confirming the agent resolves the referent
- [x] 8.3 Verify a returning-shopper scenario across two sessions: a fact stated in a session dated months ago is applied in a session opened today without being asked again, and the assistant does not disclose that it consulted memory
- [x] 8.4 Verify the retention divergence end to end: open a session with a one-minute retention, hold a conversation in which the shopper states a durable fact, wait out the minute, then confirm cross-session recall returns the fact and none of the conversation
- [x] 8.5 Verify graceful degradation by stopping the Agent Memory container mid-conversation: the shopper still receives answers and the failure is logged
- [x] 8.6 Verify signed-out behaviour is unchanged: no recall, no writes, stateless answers
- [x] 8.7 Verify no block reaches the store without a `type` annotation, by searching cross-session with each filter and confirming the two counts sum to the unfiltered total
- [x] 8.8 Run the full backend suite (`pytest` from `backend/`) and confirm it passes without a live cluster or memory server
