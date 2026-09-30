from unittest.mock import AsyncMock, patch

import pytest

from agents import user_mcp_server


@pytest.fixture(autouse=True)
def _no_real_mcp_server():
    """Keep the app lifespan from launching `uvx couchbase-mcp-server` in tests.

    Tests of the restart logic build their own PersistentMCPSession instead.
    """
    with (
        patch.object(user_mcp_server, "tools", AsyncMock(return_value=[])),
        patch.object(user_mcp_server, "close", AsyncMock()),
    ):
        yield
