## Why

The shopping assistant's memory is currently one-dimensional: every conversational turn is written to Couchbase Agent Memory with no expiry, and recall is a single semantic search scoped to the session in progress. Nothing survives a session in a usable form, nothing is ever forgotten, and a returning shopper is met by an assistant that knows nothing about them. For a demo whose point is that Couchbase Agent Memory is a *persistent* memory layer, the most compelling behaviour — the shop remembering who you are across visits — is exactly the behaviour that is missing.

## What Changes

**Write path**

- Message blocks are written with a 90-day TTL instead of living forever. Session-level default via `create_session(memory_blocks_ttl=...)`, so the raw chat transcript decays while the durable signal does not.
- After each answer, a dedicated LLM judge inspects the turn for durable shopper facts (size, favourite brand, colour preference, budget band). When it finds one, the fact is written as a separate `add_memory(facts=[...])` call with TTL 0 so it never expires. The Agent Memory SDK rejects `messages` and `facts` in one request, so these are necessarily two calls.
- Turns that contain no durable fact incur no fact write.
- Every block is written with a `type` annotation — `turn` for message blocks, `fact` for fact blocks — so the two kinds can be retrieved independently.
- Two presenter controls in the chat panel, for driving the demo live:
  - **Session date** — dates the session in progress into the past. Blocks written during that session carry the chosen date as `created_at` while everything else is recorded normally, so a conversation that appears to have happened months ago can be created on stage.
  - **Message retention** — sets how long this session's message memories survive. Because retention is fixed when the session is created, it must be set before the first message is sent; the control makes that constraint visible. Facts are unaffected, since their own retention of "never" overrides the session's — which is the point: set a short retention, watch the transcript disappear, and see the shopper's stated preferences survive.

**Read path**

- In-session recall becomes a sliding window rather than a single search: the most recent turns are supplied verbatim, older turns are compressed, and past a threshold recall switches to semantic search. This preserves the concrete referents ("the black one", a price, a SKU) that a webshop follow-up depends on, which a blanket switch to summaries destroys.
- Cross-session recall runs alongside it, scoped with `filters.session_ids="all"`, returning compressed context from earlier visits and any stored facts. It is two searches rather than one: facts and conversational turns are retrieved as separate filtered searches on the `type` annotation, each with its own budget, so a chatty past session cannot crowd out a stored preference. With in-session recall that makes three searches per turn, issued concurrently.
- Recalled blocks render from `contexts` when present, falling back to `summary`, then to the raw message. Today roughly one block in five comes back `extraction_failed` with `summary` and `contexts` both null but still fully searchable, so a summary-only renderer would contribute empty lines to the prompt.
- Facts are rendered with their `created_at` timestamp and the agent is instructed to prefer the most recent when facts conflict. The Agent Memory server does **not** resolve contradictions; it stores timestamps and leaves resolution to the agent.
- Recalled memories are presented to the agent as leads, not as results. Compression drops URLs, so a product named in a recalled conversation reaches the agent with no SKU behind it — and the agent will invent one rather than admit it has none. The memory prompt therefore states that these are records of past conversations rather than catalogue data, and that any product mentioned in them must be looked up before it is named, with price, SKU and sizes taken only from the tool result. A remembered price is stale by construction; quoting one back is worse than not remembering it.

**Explicitly out of scope**

- Annotations beyond `type`. The `source` (chat / purchase / return), `fact_kind` (size / brand / colour / budget), `department` and `pii` annotations we identified stay out of this change; only the `type` annotation that separates facts from turns is in scope. The retrieval path is built around annotation filtering, so adding the others later is additive.
- Supersede-on-write conflict resolution (searching for and updating near-duplicate facts). Contradictions are handled in the prompt instead.
- Raising the server's extraction model. The `extraction_failed` rate is treated as a condition to render defensively around, not to fix here.

## Capabilities

### New Capabilities

- `agent-memory`: What the shopping assistant remembers about a signed-in shopper, how long each kind of memory survives, and what is recalled into the agent's context on a given turn — covering fact extraction and storage, message retention, in-session recall, cross-session recall, memory rendering, and degradation when the memory server is unavailable.

### Modified Capabilities

None. No spec exists under `openspec/specs/` yet; this change introduces the first one.

## Impact

- **Code (frontend)**: [frontend/components/ChatbotPanel.tsx](frontend/components/ChatbotPanel.tsx) gains the two presenter controls and [frontend/lib/assistant.ts](frontend/lib/assistant.ts) carries the session date, the retention value and the turn count to the backend.
- **Code (backend)**: [backend/agents/user_agent.py](backend/agents/user_agent.py) carries all of it today — `MEMORY_BLOCK_TTL`, `_ensure_session`, `_format_memories`, `_memory_context`, and the recall/write sequence inside `run_agent`. The read path grows enough structure that the memory concerns likely move out into their own module.
- **Behaviour**: Signed-out shoppers stay stateless — unchanged. Signed-in shoppers gain cross-visit recall.
- **Latency**: Three recall searches per turn instead of one (three embedding round trips — to be issued concurrently), plus one LLM judge call per turn on the write path, after the answer is returned so first-token latency is unaffected.
- **Dependencies**: No new packages. Uses `agentmemory` SDK surface already installed — `add_memory(facts=...)`, `FilterOptions(session_ids, relevant_k)`, `create_session(memory_blocks_ttl=...)`.
- **Demo**: A 90-day retention is invisible on stage, and a returning shopper needs a past that predates the demo. The two presenter controls cover both, and they are not interchangeable — backdating `created_at` does not backdate expiry, which is computed at write time. Dating a session tells the "you remembered me" story; shortening retention tells the "transcript decays, facts persist" story.
- **Scope note**: This application exists for demonstration, so both controls are permanent parts of it rather than gated behind a flag. Neither is appropriate for a production shop, where a client must not choose stored timestamps or retention.