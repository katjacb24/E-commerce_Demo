# AI Data Plane Model Service (Capella-hosted models)

Capella hosts an **embedding model** and an **LLM** behind an OpenAI-compatible
API. Three parts of the demo consume them, configured independently.

| Consumer | Configured by | Provider today |
|---|---|---|
| Vector search query embedding | `CAPELLA_AI_ENDPOINT`, `CAPELLA_EMBEDDING_MODEL` | **Capella** |
| Agent Memory — embeddings, summaries, context extraction | `AGENTMEMORY_EMBEDDING_*`, `AGENTMEMORY_LLM_*` | **Capella** |
| The two agents + the fact judge | `OPEN_AI_MODEL` | **OpenAI** — Capella wired but commented out |
| Capella vectorization workflow | chosen in the Capella UI | **Capella** |

## 1. Query embedding for vector search

`backend/services/embeddings.py` posts to `/v1/embeddings` and returns the
vector [vector search](vector-search.md) hands to SQL++.

- **Endpoint resolution is forgiving** — `CAPELLA_AI_ENDPOINT` may be the bare
  host, `.../v1`, or the full `.../v1/embeddings`.
- **Auth is either/or** — `CAPELLA_AI_API_KEY` as a bearer token, or, if blank,
  `COUCHBASE_USERNAME`/`COUCHBASE_PASSWORD` as Basic auth.
- **Responses are read flexibly** — the OpenAI `data[0].embedding` shape plus the
  flatter `embeddings` and `embedding` shapes.

Each failure produces a `502` naming what to check — endpoint reachability
(`ConnectError`), cold start or `CAPELLA_AI_TIMEOUT_SECONDS` (`TimeoutException`),
model name and API key plus the body (`HTTPStatusError`), the truncated body
(unrecognised shape), or the model name (empty vector). Messages are printed to
the terminal as well as returned, since the app configures no logging handlers.
Missing configuration is a `500`, as nothing was sent.

## 2. Agent Memory's models

Set in `agent_memory/.env`, read by the Agent Memory container rather than the backend.

The embedding model makes memory *searchable* (cross-visit recall is a vector
search over memory blocks); the LLM generates each block's summary and contexts,
which is what compressed recall renders. See [Agent memory](agent-memory.md).
These need not match the app's own embedding model.

## 3. The agents' LLM — currently OpenAI

`admin_agent.py`, `user_agent.py` and `_judge_llm()` in `services/memory.py`
each construct `ChatOpenAI` against `OPEN_AI_MODEL`, with the Capella
alternative present as a **commented-out** block beside it. So the Capella LLM
is demonstrated by the Agent Memory server, not by the agents.

### Switching the agents to a Capella-hosted LLM

Set in `backend/.env`, then in each of the three files comment out the OpenAI
line and uncomment the block below it.

- **The three are independent.** The fact judge only emits a short JSON array,
  so it can stay on a cheaper model.
- **Tool-calling quality matters most here.** Both agents are ReAct loops over
  MCP tools; a weaker model will visibly loop, skip schema inspection, or invent
  field names. 

## Out of scope

Model Service value add-on feature (e.g. guardrails).