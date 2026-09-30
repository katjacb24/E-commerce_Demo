from __future__ import annotations

import asyncio
import io
import unittest
from contextlib import asynccontextmanager, redirect_stdout
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from agents import user_agent as ua

TOOL = SimpleNamespace(name="run_sql_plus_plus_query")


class _FakeClient:
    """Stands in for MultiServerMCPClient, counting server starts and stops."""

    def __init__(self, fail_starts: int = 0):
        self.started = 0
        self.stopped = 0
        self.sessions: list[AsyncMock] = []
        self._fail_starts = fail_starts

    @asynccontextmanager
    async def session(self, server_name):
        if self._fail_starts:
            self._fail_starts -= 1
            raise RuntimeError("uvx exploded")
        self.started += 1
        session = AsyncMock()
        self.sessions.append(session)
        try:
            yield session
        finally:
            self.stopped += 1


def _run(coro_fn, client):
    """Run `coro_fn(mcp)` against a fresh PersistentMCPSession, then close it."""

    async def main():
        mcp = ua.PersistentMCPSession(client, "couchbase")
        try:
            return await coro_fn(mcp)
        finally:
            await mcp.close()

    with (
        patch.object(ua, "load_mcp_tools", AsyncMock(return_value=[TOOL])),
        redirect_stdout(io.StringIO()),
    ):
        return asyncio.run(main())


class PersistentMCPSessionTests(unittest.TestCase):
    def test_server_is_started_once_and_reused_across_questions(self):
        client = _FakeClient()

        async def ask_three_times(mcp):
            return [await mcp.tools() for _ in range(3)]

        results = _run(ask_three_times, client)
        self.assertEqual(results, [[TOOL]] * 3)
        self.assertEqual(client.started, 1)

    def test_server_that_stops_answering_is_replaced(self):
        client = _FakeClient()

        async def die_between_questions(mcp):
            await mcp.tools()
            client.sessions[0].send_ping.side_effect = ConnectionError("pipe closed")
            return await mcp.tools()

        self.assertEqual(_run(die_between_questions, client), [TOOL])
        self.assertEqual(client.started, 2)
        # The dead server was torn down before its replacement took over.
        self.assertEqual(client.stopped, 2)  # dead one on restart, new one on close

    def test_concurrent_questions_at_a_dead_server_start_one_replacement(self):
        client = _FakeClient()

        async def die_then_ask_concurrently(mcp):
            await mcp.tools()
            client.sessions[0].send_ping.side_effect = ConnectionError("pipe closed")
            await asyncio.gather(*(mcp.tools() for _ in range(3)))

        _run(die_then_ask_concurrently, client)
        self.assertEqual(client.started, 2)

    def test_failed_start_surfaces_and_the_next_question_retries(self):
        client = _FakeClient(fail_starts=1)

        async def fail_then_retry(mcp):
            with self.assertRaises(RuntimeError):
                await mcp.tools()
            return await mcp.tools()

        self.assertEqual(_run(fail_then_retry, client), [TOOL])
        self.assertEqual(client.started, 1)

    def test_caller_cancelled_mid_start_leaves_a_working_server(self):
        client = _FakeClient()

        async def cancel_first_caller(mcp):
            first = asyncio.create_task(mcp.tools())
            await asyncio.sleep(0)  # let it begin starting the server
            first.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await first
            return await mcp.tools()

        self.assertEqual(_run(cancel_first_caller, client), [TOOL])
        # The server the cancelled caller started is the one reused.
        self.assertEqual(client.started, 1)

    def test_close_stops_the_server(self):
        client = _FakeClient()
        _run(lambda mcp: mcp.tools(), client)
        self.assertEqual(client.stopped, 1)


if __name__ == "__main__":
    unittest.main()
