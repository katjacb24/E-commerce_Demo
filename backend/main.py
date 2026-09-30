from contextlib import asynccontextmanager
import logging
import threading
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agents import user_mcp_server
from db.connection import initialize_couchbase, shutdown_couchbase
from routers import agent_router, assistant_router, products_router


logger = logging.getLogger(__name__)

# Floor between reconnect attempts so a sustained outage cannot turn every
# inbound request into its own 30s bootstrap attempt.
RECONNECT_COOLDOWN_SECONDS = 10.0


def _connect_couchbase(app: FastAPI) -> bool:
    """Establish the Couchbase connection and publish handles on app state."""
    try:
        cluster, bucket, scope, collection = initialize_couchbase()
    except Exception:
        logger.exception("Couchbase connection attempt failed.")
        return False

    app.state.couchbase_cluster = cluster
    app.state.couchbase_bucket = bucket
    app.state.couchbase_scope = scope
    app.state.couchbase_collection = collection
    app.state.couchbase_available = True
    return True


def _build_reconnector(app: FastAPI):
    """Return a thread-safe, rate-limited (re)connect callable.

    Product endpoints call this while degraded so a transient Couchbase outage
    heals on its own instead of pinning the API to 503 until it is restarted.
    """
    lock = threading.Lock()
    last_attempt: list[float | None] = [None]

    def reconnect() -> bool:
        if app.state.couchbase_available:
            return True
        with lock:
            # Re-check under the lock: a concurrent caller may have just won.
            if app.state.couchbase_available:
                return True
            now = time.monotonic()
            previous = last_attempt[0]
            if previous is not None and now - previous < RECONNECT_COOLDOWN_SECONDS:
                return False
            last_attempt[0] = now
            return _connect_couchbase(app)

    return reconnect


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Connect during startup, then keep the same path available for retries.
    app.state.couchbase_available = False
    app.state.couchbase_cluster = None
    app.state.couchbase_reconnect = _build_reconnector(app)

    if not app.state.couchbase_reconnect():
        logger.warning(
            "Couchbase is unavailable. API started in degraded mode; product "
            "endpoints will return 503 and retry the connection on demand."
        )

    # Warm the personal assistant's MCP server so the first question does not
    # pay its startup. A failure is not fatal: the first question retries it.
    try:
        await user_mcp_server.tools()
    except Exception:
        logger.exception("MCP server failed to start; the first assistant question will retry.")

    try:
        yield
    finally:
        await user_mcp_server.close()
        if app.state.couchbase_cluster is not None:
            shutdown_couchbase(app.state.couchbase_cluster)


app = FastAPI(title="DemoShop API", lifespan=lifespan)

# Frontend app runs on port 3000 during local development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agent_router)
app.include_router(assistant_router)
app.include_router(products_router)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
