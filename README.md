# DemoWebshop

A demo web shop built on **Couchbase Capella**, used to show the Data, Query,
Search and vector-search services alongside the Capella AI Data Plane (Data
processing and Vectorization Workflow, Model Service, MCP Server and Agent
Memory) — in one working application.

**This repository is for demo purposes only.**

A monorepo with:

- `frontend/` — Next.js (TypeScript, App Router, Tailwind CSS)
- `backend/` — FastAPI service exposing the Couchbase-backed product catalogue:
  paginated listing with filters and sorting, filter facets, full-text search,
  natural-language vector search, product detail by SKU, two LangGraph agents,
  and a health endpoint
- `agent_memory/` — deployment artifacts for the Agent Memory server container

## What it demonstrates

| Surface | Couchbase capability |
|---|---|
| Product listing, filters, sorting, facets | SQL++ over GSI indexes (Couchbase Index + Query Services) |
| Product detail page | key-value lookup (Couchbase Data Service) |
| The search bar | full-text search (Couchbase Search Service) |
| *"Describe what you are looking for"* in the sidebar | vector search over text embeddings, vector GSI index + Capella-hosted embedding model (Couchbase Index + Query Services + Couchbase AI Data Plane Model Service) |
| The shop's chat assistant | MCP Server + Agent Memory (Couchbase AI Data Plane) |
| Admin → Operations Dashboard | MCP Server (Couchbase AI Data Plane) |

Both search modes (FTS request and a vector SQL++ statement) expose the
**exact query Couchbase ran** behind an ℹ️ button.

## Documentation

Start here for the complete picture of which Couchbase services are used:

- **[Couchbase services in this demo](docs/couchbase-services.md)** — the
  (in scope and out of scope) service map

Then per topic:

- [Data & Query](docs/data-and-query.md) — KV access, SQL++, GSI indexes, the data model
- [Full-text search](docs/full-text-search.md) — the FTS index mapping and the query against it
- [Vector search](docs/vector-search.md) — the vector index, embedding round trip, the Capella vectorization workflow
- [Model service](docs/model-service.md) — Capella-hosted embedding and LLM endpoints
- [MCP](docs/mcp.md) — the Couchbase MCP Server, the admin agent and the Personal Assistant
- [Agent memory](docs/agent-memory.md) — retention, recall, facts vs. turns

---

# Run the Demo locally

## Prerequisites

- Node.js 20+
- npm 10+
- Python 3.11+
- Docker (only for [Agent Memory](docs/agent-memory.md))
- `uv` / `uvx` on `PATH` (only for the [MCP](docs/mcp.md) agents) —
  `pip install uv` or `brew install uv`

## Set up a Couchbase Capella Cluster

1. Create a Couchbase Capella cluster with the name "DemoWebshop"
2. Create a bucket ("webshop"), scope ("webshop-scope") and collection ("products")
3. Allow the IP address (in Capella UI: Settings → Allowed IP Addresses)
4. Create a database user ("capellaAdmin") with the Read & Write access to All
   Buckets, All Scopes and All Collections (in Capella UI: Settings → Access
   Control)
5. Copy the connection string (in Capella UI: Connect → SDKs → Public
   Connection String) to later paste it into `backend/.env` file.

## Frontend (Next.js)

1. Install dependencies:
   ```bash
   cd frontend
   npm install
   ```
2. Create and fill in local env file:
   ```bash
   cp .env.example .env
   ```
3. Start development server (port 3000):
   ```bash
   npm run dev
   ```
4. Open the app UI:
   `http://localhost:3000`

## Backend (FastAPI)

1. Create and activate virtual environment:
   ```bash
   cd backend
   python3 -m venv .venv
   source .venv/bin/activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Create local env file:
   ```bash
   cp .env.example .env
   ```
4. Start API server (port 8000):
   ```bash
   uvicorn main:app --reload
   ```
5. Backend docs:
   `http://localhost:8000/docs`
6. (Optional) Health Check - when backend is running, verify:
   ```bash
   curl http://localhost:8000/health
   ```
   Expected response:
   ```json
   {"status":"ok"}
   ```

   The API starts even when Couchbase is unreachable, in degraded mode: product
   endpoints answer `503` and retry the connection on demand. See
   [Data & Query](docs/data-and-query.md#connection-handling).

7. (Optional) Run the backend tests
   From `backend/` (the venv must be active, or use `./.venv/bin/python -m pytest`):
   ```bash
   pytest
   ```
   The suite mocks Couchbase, so it needs no cluster and no `.env`.

## Load seed data and create indexes (GSI and FTS) in Couchbase

1. Add the product images. Each document in `backend/seed_data/products.json`
   references its image by bare filename (e.g. `"image": "39773.jpg"`), resolved
   against `NEXT_PUBLIC_PRODUCT_IMAGE_BASE_URL`. So the images have to line up
   with the seed file **before** you seed:
   ```bash
   mkdir -p frontend/public/product-images
   ```
   - **If you have this demo's image set:** copy all of it into that folder. The
     filenames already match the seed file, so there is nothing to edit.
   - **If you do not:** copy your own images into that folder, then edit the
     `image` field of each entry in `backend/seed_data/products.json` to match
     your filenames. Any entry whose `image` has no matching file renders with a
     broken image.
2. Seed demo product data into Couchbase (from the project's root directory):
   ```bash
   ./backend/.venv/bin/python backend/scripts/seed_data.py
   ```
   Reads `backend/seed_data/products.json` and upserts each document under a
   `product::<sku>` key, using the bucket/scope/collection from `backend/.env`.
   Re-run it after any edit to the seed file.
3. Create the query and search indexes (from the project's root directory):
   ```bash
   ./backend/.venv/bin/python backend/scripts/create_indexes.py
   ```
   Safe to re-run — existing indexes are left untouched. It creates:
   - **GSI:** `idx_products_primary` (primary), plus secondary indexes on
     `category.department`, `category.type`, `category.subtype`, `color`,
     `price.amount` and `name`. See
     [Data & Query](docs/data-and-query.md#the-indexes).
   - **FTS:** a scope-level index named after `COUCHBASE_FTS_INDEX` (default
     `products_search`), with an explicit — not dynamic — mapping. See
     [Full-text search](docs/full-text-search.md#the-index).

## AI Data Plane — Model Service

1. In Capella UI, navigate to AI Data Plane → Models.
2. Deploy an embedding model of your choosing out of the available models.
   - Create an API key for your model.
   - **Fill in `backend/.env`:**
     ```bash
     CAPELLA_AI_ENDPOINT=https://<your-endpoint>.ai.cloud.couchbase.com  # Model Endpoint URL
     CAPELLA_AI_API_KEY=<your-api-key>
     CAPELLA_EMBEDDING_MODEL=<model>
     CAPELLA_AI_TIMEOUT_SECONDS=20
     ```
3. (Optional) Deploy an LLM of your choosing out of the available models.
   - Create an API key for your model.
   - **Fill in `backend/.env`:**
     ```bash
     LLM_BASE_URL=https://<your-endpoint>.ai.cloud.couchbase.com/v1  # Model Endpoint URL
     LLM_API_KEY=<your-api-key>
     LLM_MODEL=<model>
     ```

## AI Data Plane — Data Processing and Vectorization Services

Vectorize the products in the Capella UI. There is no code for this in the repo,
it is a managed workflow in Capella over JSON data already seeded in the cluster.

### Prerequisites

- Products already seeded (see above).

### Steps

1. In Capella UI, navigate to AI Data Plane → Workflows.
2. Create a new **Data from Capella** Workflow with the name of your choosing.
3. Select "DemoWebshop" cluster, "webshop" bucket, "webshop-scope" scope and
   "products" collection as the Data Source.
4. Create custom source field mappings - select the **descriptive text fields** —
   the ones that describe what a product *is*: `name`, `description`,
   `material`, `tags`, `color` and the `category`. Set the output field name to
   **`descriptive_vectors`**.
5. Choose "Create Hyperscale Vector Index (later)". The vector index is created
   by hand in the next section.
6. Choose "Capella Model" as Model Source and enter its API Key ID and API Key
   Token.
7. Optionally set up private networking (not required for this demo).
8. Run the workflow and wait until all the documents are vectorized.

## Enable natural-language Vector Search

Powers the sidebar's *"Describe what you are looking for"* box.

### Steps

1. In the Capella UI (Query workbench), **create the vector index** over the
   `descriptive_vectors` field:
   ```sql
   CREATE INDEX `composite_descriptive_vectors`
     ON `webshop`.`webshop-scope`.`products`(`descriptive_vectors` VECTOR)
     WITH { "defer_build":false, "dimension":2048, "similarity":"l2_squared", "description":"IVF,SQ8" };
   ```
   - `dimension` **must** match the output size of the embedding model you chose.
   - `similarity` is the metric — **note it**, it goes into `backend/.env` below.
   - `defer_build:false` builds the index immediately. (Capella's generated
     definition uses `true`, which only registers the definition and needs a
     separate `BUILD INDEX ON ...(composite_descriptive_vectors)` afterwards —
     useful when creating several indexes at once so they share one scan, but
     unnecessary for a single index.)

   Confirm it reaches `online` before moving on:
   ```sql
   SELECT name, state FROM system:indexes WHERE name = "composite_descriptive_vectors";
   ```

   > **One index, on the vector field only.** The sidebar filters
   > (`category.department`, `color`, `price.amount`, …) are all *optional*, and
   > a GSI index is only eligible when the query filters on its **leading key** —
   > so adding scalar fields ahead of the vector key would make the index
   > unusable on any search that leaves those filters blank. One vector-only
   > index covers every combination instead.
   >
   > The trade-off: filters are applied **after** the nearest-neighbour scan, not
   > pushed into it. `topK` selects the nearest matches across the whole
   > collection and the `WHERE` clause then drops the ones that do not match, so
   > a narrow filter can return fewer results than `topK` — occasionally none —
   > even when matching products exist. Widen the filters or raise `topK` if that
   > shows up during a demo.

2. **Fill in `backend/.env`:**
   ```bash
   COUCHBASE_VECTOR_INDEX=composite_descriptive_vectors   # the index from step 1
   COUCHBASE_VECTOR_METRIC=L2_SQUARED                     # MUST match `similarity` in step 1
   ```

3. **Restart the backend** and verify vector search in the Application UI by
   typing your natural-language query in the sidebar's *"Describe what you are
   looking for"* box. In the UI, the ℹ️ button next to the results heading shows
   the executed SQL++ statement.

## Enable the agents (MCP) and Agent Memory

Two agents, both reaching Couchbase database **only** through the Couchbase MCP
Server: the **Operations Dashboard** agent (*Admin* in the nav bar) and the
**Personal Assistant** (the chat bubble). Only the Personal Assistant uses Agent
Memory.

### Prerequisites

- `uv` / `uvx` on `PATH` — `pip install uv` or `brew install uv`. The MCP server
  itself is deliberately *not* a dependency of this project: `uvx
  couchbase-mcp-server` runs it in its own isolated environment, so its
  dependencies cannot conflict with the backend's.
- An **LLM**: either an OpenAI API key, or a Capella-hosted LLM.
- **Docker** and the Agent Memory image `.tar` stored in the `agent_memory/`
  directory — for Part B only.

### Part A — the agents

1. **Verify `uvx`:**
   ```bash
   uvx --version
   ```

2. **Configure the LLM** in `backend/.env`. In this project, both agents run on
   OpenAI:
   ```bash
   OPENAI_API_KEY=<your-key>
   OPEN_AI_MODEL=<model>
   ```
   To use a **Capella-hosted LLM** instead, set `LLM_BASE_URL`, `LLM_API_KEY`
   and `LLM_MODEL` as described in section "AI Data Plane — Model Service"
   Step 3 above and then in **both** `backend/agents/admin_agent.py` and
   `backend/agents/user_agent.py`, comment out the
   `ChatOpenAI(model=os.getenv("OPEN_AI_MODEL"), ...)` line and uncomment the
   Capella block directly below it.

   The fact judge that Agent Memory uses has the same pair of blocks, in
   `_judge_llm()` in `backend/services/memory.py`. Switch it too, or leave it on
   OpenAI — it is configured independently of the agents on purpose, so the
   judge can run on a cheaper model.

3. **Restart the backend** and verify:
   ```bash
   curl -X POST http://localhost:8000/api/agent/chat \
     -H 'Content-Type: application/json' \
     -d '{"query":"How many products are in the catalogue?"}'
   ```
   The first call is slow while `uvx` resolves and caches the MCP server's
   environment; later calls reuse it.

4. **Try it in the UI.** *Admin* in the nav bar opens the Operations Dashboard.
   **Trigger Checks** runs the cluster-health and query-diagnostics checks
   through the agent, which then follows its own findings up with further tool
   calls — the index advisor on a slow statement, for instance — and reports a
   finding and a recommendation per tool call; **Show details** on any reply
   opens the real MCP tool trace behind it.

The MCP server is always launched read-only, and the Personal Assistant runs
with an additional disabled-tool list. See [MCP](docs/mcp.md).

### Part B — Agent Memory

The memory server runs as its **own Docker container** and stores its memory
blocks in a **separate bucket** on the same Capella cluster. Without it the
assistant still answers, just without recall — memory is an enhancement, never
a dependency.

1. **Create the bucket** in Capella (`agent_memory`). The server creates and
   manages its own scopes and collections inside it.

2. **Download the Capella security certificate** (Capella UI → Settings →
   Security Certificate → Download), rename it into `ca.pem`, and put it in
   `agent_memory/` directory inside this project.

3. **Fill in `agent_memory/.env`** (copy from `agent_memory/.env.example`).
   The embedding model is what makes memory searchable; the LLM generates each
   block's summary and extracted contexts. Both are configured separately from
   the application's own models and need not be the same ones.

4. **Load the Docker image and start the Agent Memory Server**, from
   `agent_memory/` — the `docker run` below uses `$(pwd)` and
   `--env-file .env`, so the working directory matters:
   ```bash
   cd agent_memory
   docker load -i agentmemory-server-arm64-v1.0.0.tar
   docker run -d \
     -v $(pwd)/ca.pem:/app/certs/ca.pem:ro \
     --name agentmemory-server \
     --env-file .env \
     -p 8080:8080 \
     -p 9090:9090 \
     -v agentmemory-logs:/app/logs \
     --restart unless-stopped \
     agentmemory-server:v1.0.0
   ```
   To start over: `docker rm -f agentmemory-server`, then re-run.

5. **Nothing to install.** The Agent Memory Python SDK
   (`couchbase-agent-memory`) is already pulled in by
   `backend/requirements.txt`, so the backend venv created earlier has it.

6. **Verify the Agent Memory Server is healthy:**
   ```bash
   curl http://localhost:8080/health     # API docs at http://localhost:8080/docs or http://localhost:8080/redoc
   docker logs agentmemory-server        # check the logs if it is not healthy
   ```

7. **Point the backend at it** in `backend/.env`: adjust the default values if
   needed and restart the backend.

8. **Try it.** Demo logins are hardcoded with **emily / 123** and
   **john / 123** users. 
   Memory is recorded for a **signed-in** shopper only —
   for signed out users, the assistant is stateless by design. Closing and
   reopening the chat panel starts a new session, which is how a return visit is
   simulated.