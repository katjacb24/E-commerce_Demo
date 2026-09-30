# AI Data Plane MCP Server (Couchbase MCP Server)

Both agents reach Couchbase **only** through the Couchbase MCP Server — no
hand-written database tools, no Couchbase SDK handle. Every lookup is an MCP tool call.

## How it is run

The MCP server is **not** a dependency of this project: `requirements.txt`
installs `uv`, and `uvx couchbase-mcp-server` runs it in its own isolated
environment, launched as a **stdio subprocess** that the LangChain adapter
spawns and turns into LangChain tools.

```python
MCP_SERVERS = {"couchbase": {
    "transport": "stdio",
    "command": UVX,                       # UVX_PATH, or shutil.which("uvx")
    "args": ["couchbase-mcp-server"],
    "env": {**os.environ,                 # uvx needs PATH/HOME for its cache
            "CB_CONNECTION_STRING": ...,  # the server reads CB_*; this project's
            "CB_USERNAME": ...,           # .env uses COUCHBASE_*, mapped at launch
            "CB_PASSWORD": ...,
            "CB_MCP_READ_ONLY_MODE": "true"}}}
```

The two agents keep their server process alive for different lengths of time:

- **Admin agent — one process per request.** It starts with the run and is torn
  down on exit. Runs are long and rare, so the ~1s startup barely registers.
- **Personal Assistant — one long-lived process.** `PersistentMCPSession`
  starts it when the backend starts and reuses it for every question, so chat
  turns skip the startup. Before each question it pings the server and restarts
  it if the ping fails; it is stopped when the backend shuts down.

Each agent has its own process and tool set, so neither can reach the other's
tools. Read-only mode is on for both agents, always.

## Two agents, two tool profiles

| | Admin agent | Personal Assistant |
|---|---|---|
| File | `backend/agents/admin_agent.py` | `backend/agents/user_agent.py` |
| Endpoint | `POST /api/agent/chat` | `POST /api/assistant/chat` |
| UI | Admin → Operations Dashboard | the chat bubble in the web shop |
| Tools | **all** of them | a restricted subset |
| MCP server process | started per request | long-lived, restarted if it dies |
| Persona | Couchbase data analyst / DevOps engineer | customer assistant |
| MCP trace returned to UI | **yes** | no (terminal only) |
| Agent Memory | no | yes — see [Agent memory](agent-memory.md) |

**Admin agent — full tool set**: schema discovery, document lookup by id, SQL++
execution, cluster connection and health checks, index listing, index advisor,
and the query-monitoring tools (longest-running, most frequent, non-selective,
not using a covering index, using only the primary index, largest response sizes
and result counts). Its prompt pins this app's bucket/scope/collection/FTS index
and requires it to **inspect the collection schema before writing a query**.

**Personal Assistant — narrowed on purpose**: the same server started with
`CB_MCP_DISABLED_TOOLS`, leaving only schema inspection, document lookup by id
and SQL++ execution. Disabled: all writes (`upsert`/`insert`/`replace`/
`delete_document_by_id`), all cluster introspection
(`get_server_configuration_status`, `test_cluster_connection`,
`get_cluster_health_and_services`), and all query diagnostics and index tooling
(`explain_sql_plus_plus_query`, `list_indexes`,
`get_index_advisor_recommendations`, the seven monitoring tools).

Its prompt reinforces the same boundary: decline write requests politely, never
reveal bucket/scope/collection names or data volumes, never suggest SQL++ to a
customer, never print a document id or SKU as visible text. **Defence in depth
is the point** — read-only mode, the disabled-tool list and the prompt are three
layers, and an injection defeating the prompt still meets the other two.

**Product links**: the assistant must select `sku` alongside `meta().id` and
render products as `[Product Name](/products/<sku>)` — bare SKU, no `product::`
prefix — and link one only when that SKU came back from a tool call, so it
cannot link using a SKU inferred from a remembered name. Rendered by
`frontend/components/Markdown.tsx`.

## The Operations Dashboard

`Admin` in the navigation bar opens a three-pane view
(`frontend/components/Layout/AdminView.tsx`): **Alerts** (the latest check run),
**Chat** (free-form questions), **Details** (the trace behind the selected run
or reply).

### Trigger Checks

**Trigger Checks** posts to `/api/agent/checks`, which is `run_cluster_checks()`
in `backend/agents/admin_agent.py` — a separate endpoint from `/chat` because
the run is **two passes**, not one.

**Pass 1 — the agent runs the checks** (`CLUSTER_CHECKS_QUERY`), in three steps
it is told to take in order:

1. *Baseline.* Cluster connection and health, long-running queries,
   non-selective queries, queries not using a covering index, queries using only
   the primary index, queries with the largest response sizes and result counts.
2. *Follow-up.* Work out how the baseline findings relate to one another — the
   same statement coming back as both long-running and non-selective is one
   problem, not two — then call whatever further tools each problem calls for:
   `list_indexes` on the collection a slow query reads,
   `get_index_advisor_recommendations` on that exact statement,
   `explain_sql_plus_plus_query` on its plan. Clean checks get no follow-up.
3. *Report.* What each problem is, which tool call shows it, and what to do.

This is what makes the run an agent rather than a script: which tools run in
step 2, and against which statements, is decided from what step 1 returned. 

**Pass 2 — the reporting pass** (`analyse_check_run()`) is a second, *tool-free*
LLM call. It is handed the numbered trace of pass 1 — every call's arguments,
status and result, each result clipped to `RESULT_CHARS_FOR_REPORT` — and
returns structured output (`CheckReport`): one verdict per tool call, carrying a
`severity` (`critical` / `serious` / `warning` / `none`), a `finding` of at most
three sentences, and a `recommendation`. It has no tools, so it can only speak
about what the run already fetched.

The verdicts are merged back onto the calls by trace position, and a verdict
with no finding text behind it is dropped rather than colouring a call the UI
would then have to label "No findings.". `AGENT_RECURSION_LIMIT` is raised well
above LangGraph's default of 25, since the two steps together are a long loop.

### How a run is shown

One run is **one block** in the Alerts panel — `N tools run` plus a count per
severity. Selecting it opens, in order: the agent's summary, **Tools used**
(one bubble per distinct tool, coloured by the worst severity across its calls
and left neutral when it raised nothing), and **Tool calls** — each showing its
finding, then its recommendation if there is one, then arguments and result.
Each run replaces the previous one; **Acknowledge** dismisses it.

A chat reply's trace has no verdicts on it, so the finding and recommendation
sections are left out there rather than repeating "No findings." down the whole
trace. Every reply from a real run carries its trace, so **Show details** works
on past replies too. A trace shows each tool's name, arguments, result and
status — `success`, `error`, or `pending` (the call never returned because the
run was cut short).

## Tracing

`_extract_tool_calls()` (admin) and `_print_tool_calls()` (shopper) reconstruct
the run from LangGraph's transcript: an `AIMessage` carrying `tool_calls`, then
one `ToolMessage` per call referencing it by id. Results are indexed by id, then
the transcript is walked **in order**, so calls appear as the agent made them.
Results arrive as a plain string or as a list of content blocks (common for MCP
servers), both normalised by `_stringify_content()`; in the terminal they are
clipped to 2000 characters with a note saying how much was omitted.

## Out of scope

Writes through MCP · HTTP/SSE transport (stdio only) · multiple MCP servers · 
multi-node LangGraph routing (one node per graph) · conversation history for the admin agent.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `uvx not found` at import | install `uv`, or set `UVX_PATH` |
| First agent call is slow | `uvx` is caching the server's environment; later calls reuse it |
| First assistant answer after laptop sleep or a network change is slow or fails | the long-lived server's cluster connection is recovering; ask one warm-up question before the demo |
| `Agent failed: ...` (502) | the LLM call or MCP round trip failed; traceback is in the backend log |
| Agent invents field names | it skipped schema inspection — usually a weaker LLM; see [Model service](model-service.md#switching-the-agents-to-a-capella-hosted-llm) |
| Trace shows `pending` | the run was cut short (recursion limit or error) before the tool replied |
| Checks report nothing | expected on a healthy idle cluster: every tool call comes back with "No findings." |