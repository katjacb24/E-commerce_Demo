from __future__ import annotations

import asyncio
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import AsyncMock, patch

from agentmemory import AgentMemoryError

from agents import user_agent as ua


class _FakeSession:
    def __init__(self, session_id="session1", blocks_ttl=90 * 24 * 60 * 60):
        self.session_id = session_id
        self.blocks_ttl = blocks_ttl


def _run(**kwargs):
    """Drive run_agent with the agent graph and the memory server both faked.

    stdout is swallowed because the module traces every run to the terminal.
    """
    with redirect_stdout(io.StringIO()):
        return asyncio.run(ua.run_agent("black jeans?", **kwargs))


class SignedOutShopperTests(unittest.TestCase):
    def test_signed_out_shopper_gets_a_stateless_answer(self):
        with (
            patch.object(ua.app, "ainvoke", AsyncMock(return_value={"answer": "Here."})),
            patch.object(ua.memory, "memory_client") as client,
        ):
            run = _run()
        self.assertEqual(run["answer"], "Here.")
        self.assertIsNone(run["session_id"])
        self.assertEqual(run["memories"], [])
        self.assertIsNone(run["retention_seconds"])
        # No client is even opened for a shopper with no identity.
        client.assert_not_called()


class MemoryFailureTests(unittest.TestCase):
    """Memory is an enhancement; none of its failures may cost the answer."""

    def _patches(self, **overrides):
        defaults = {
            "ensure_user": AsyncMock(return_value=object()),
            "ensure_session": AsyncMock(return_value=_FakeSession()),
            "recall": AsyncMock(return_value=["The shopper wears M."]),
            "record_turn": AsyncMock(return_value=None),
            "judge_facts": AsyncMock(return_value=["The shopper wears M."]),
            "record_facts": AsyncMock(return_value=None),
        }
        defaults.update(overrides)
        return defaults

    def _run_with(self, **overrides):
        mocks = self._patches(**overrides)
        client = AsyncMock()
        with (
            patch.object(ua.app, "ainvoke", AsyncMock(return_value={"answer": "Here."})),
            patch.object(ua.memory, "memory_client", return_value=client),
            patch.multiple(ua.memory, **mocks),
        ):
            run = _run(user_id="user1", username="emily")
        return run, mocks, client

    def test_happy_path_records_the_turn_and_the_fact(self):
        run, mocks, client = self._run_with()
        self.assertEqual(run["answer"], "Here.")
        self.assertEqual(run["session_id"], "session1")
        self.assertEqual(run["retention_seconds"], 90 * 24 * 60 * 60)
        mocks["record_turn"].assert_awaited_once()
        mocks["record_facts"].assert_awaited_once()
        client.close.assert_awaited_once()

    def test_recall_failure_still_answers_without_memories(self):
        run, mocks, _ = self._run_with(
            recall=AsyncMock(side_effect=AgentMemoryError("down"))
        )
        self.assertEqual(run["answer"], "Here.")
        self.assertEqual(run["memories"], [])

    def test_judge_failure_still_answers_and_still_records_the_turn(self):
        run, mocks, _ = self._run_with(
            judge_facts=AsyncMock(side_effect=RuntimeError("llm exploded"))
        )
        self.assertEqual(run["answer"], "Here.")
        mocks["record_turn"].assert_awaited_once()
        mocks["record_facts"].assert_not_awaited()

    def test_fact_write_failure_still_answers_and_still_records_the_turn(self):
        run, mocks, _ = self._run_with(
            record_facts=AsyncMock(side_effect=AgentMemoryError("down"))
        )
        self.assertEqual(run["answer"], "Here.")
        mocks["record_turn"].assert_awaited_once()

    def test_turn_write_failure_still_answers(self):
        run, mocks, _ = self._run_with(
            record_turn=AsyncMock(side_effect=AgentMemoryError("down"))
        )
        self.assertEqual(run["answer"], "Here.")

    def test_no_fact_found_means_no_fact_write(self):
        run, mocks, _ = self._run_with(judge_facts=AsyncMock(return_value=[]))
        self.assertEqual(run["answer"], "Here.")
        mocks["record_facts"].assert_not_awaited()

    def test_client_is_closed_even_when_everything_fails(self):
        _, _, client = self._run_with(
            ensure_user=AsyncMock(side_effect=AgentMemoryError("down"))
        )
        client.close.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()


class PresenterControlTests(unittest.TestCase):
    """The session date and the retention reach the memory layer intact."""

    def _run(self, **run_kwargs):
        mocks = {
            "ensure_user": AsyncMock(return_value=object()),
            "ensure_session": AsyncMock(return_value=_FakeSession()),
            "recall": AsyncMock(return_value=[]),
            "record_turn": AsyncMock(return_value=None),
            "judge_facts": AsyncMock(return_value=["The shopper wears M."]),
            "record_facts": AsyncMock(return_value=None),
        }
        with (
            patch.object(ua.app, "ainvoke", AsyncMock(return_value={"answer": "Here."})),
            patch.object(ua.memory, "memory_client", return_value=AsyncMock()),
            patch.multiple(ua.memory, **mocks),
            redirect_stdout(io.StringIO()),
        ):
            run = asyncio.run(
                ua.run_agent("q", user_id="user1", username="emily", **run_kwargs)
            )
        return run, mocks

    def test_session_date_reaches_both_the_turn_and_the_fact_write(self):
        stamp = "2026-03-14T15:30:00"
        _, mocks = self._run(created_at=stamp)
        self.assertEqual(mocks["record_turn"].await_args.kwargs["created_at"], stamp)
        self.assertEqual(mocks["record_facts"].await_args.kwargs["created_at"], stamp)

    def test_no_session_date_files_memories_at_the_time_they_were_recorded(self):
        _, mocks = self._run()
        self.assertIsNone(mocks["record_turn"].await_args.kwargs["created_at"])
        self.assertIsNone(mocks["record_facts"].await_args.kwargs["created_at"])

    def test_retention_is_handed_to_session_creation(self):
        _, mocks = self._run(retention_seconds=60)
        self.assertEqual(
            mocks["ensure_session"].await_args.kwargs["retention_seconds"], 60
        )

    def test_retention_in_force_is_reported_from_the_session_not_the_request(self):
        # The presenter asked for 60s on a turn that did not open the session;
        # what comes back is what the session actually holds.
        run, _ = self._run(retention_seconds=60)
        self.assertEqual(run["retention_seconds"], 90 * 24 * 60 * 60)
