# Couchbase services used in this demo

Everything runs against one **Couchbase Capella** cluster: the app uses one
bucket with one scope and one collection; the Agent Memory server uses a second bucket.

## In scope

| Service | Used for | Where |
|---|---|---|
| **Data (KV)** | product detail by SKU, batch hydration of search hits, seeding | [Data & Query](data-and-query.md) |
| **Index + Query** | SQL++ listing, filters, sorting, facets, pagination, vector search | [Data & Query](data-and-query.md) |
| **Search (FTS)** | keyword search bar, and `SEARCH()` inside agent-written SQL++ | [Full-text search](full-text-search.md) |
| **Vector search** | natural-language "describe what you are looking for" search | [Vector search](vector-search.md) |
| **AI Data Plane Data Processing + Vectorization** | generating `descriptive_vectors` — **Capella UI workflow, no code in this repo** | [Vector search](vector-search.md#how-descriptive_vectors-got-there) |
| **AI Data Plane Model Service** | Capella-hosted embedding model and LLM | [Model service](model-service.md) |
| **AI Data Plane MCP Server** | the tool layer both LangGraph agents call Couchbase through | [MCP](mcp.md) |
| **AI Data Plane Agent Memory** | what the Personal Assistant remembers across visits | [Agent memory](agent-memory.md) |

**Vector search is not the Search service.** It runs `APPROX_VECTOR_DISTANCE`
in SQL++ against a vector GSI index (Index + Query). 

**FTS is reached two ways.** The search bar calls the Search service; the agents
write SQL++ with `SEARCH(p.description, "...")`, pushing a predicate into the
same index.

**The Capella-hosted models** serve vector-search query embedding (`CAPELLA_EMBEDDING_MODEL`) 
and Agent Memory (`AGENTMEMORY_LLM_MODEL`, `AGENTMEMORY_EMBEDDING_MODEL`). 
The two agents and the fact judge run on **OpenAI** (`OPEN_AI_MODEL`); the Capella alternative is wired 
but commented out — see [Model service](model-service.md#switching-the-agents-to-a-capella-hosted-llm).

## Out of scope

Eventing · AI Functions · Agent Catalog · image embeddings · Couchbase Analytics · XDCR, backup/restore, scaling.