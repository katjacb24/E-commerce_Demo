from __future__ import annotations

import unittest
from datetime import date, datetime
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from routers.assistant import _resolve_created_at, _resolve_retention, router


def _client() -> TestClient:
    """A client over just the assistant router, so no Couchbase lifespan runs."""
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _run_result(**overrides):
    result = {
        "answer": "Here.",
        "session_id": "session1",
        "retention_seconds": 7776000,
        "memories": [],
        "user_query": "q",
    }
    result.update(overrides)
    return result


class CreatedAtResolutionTests(unittest.TestCase):
    def test_absent_date_yields_no_override(self):
        self.assertIsNone(_resolve_created_at(None))
        self.assertIsNone(_resolve_created_at("   "))

    def test_valid_date_keeps_the_day_and_takes_the_clock_time(self):
        resolved = _resolve_created_at("2026-03-14")
        parsed = datetime.fromisoformat(resolved)
        self.assertEqual(parsed.date(), date(2026, 3, 14))
        # Time of day tracks the real clock so turns stay ordered.
        self.assertEqual(parsed.hour, datetime.now().hour)

    def test_malformed_date_is_rejected_rather_than_ignored(self):
        from fastapi import HTTPException

        for bad in ("14-03-2026", "not-a-date", "2026-13-45"):
            with self.assertRaises(HTTPException) as caught:
                _resolve_created_at(bad)
            self.assertEqual(caught.exception.status_code, 422)


class RetentionResolutionTests(unittest.TestCase):
    def test_absent_retention_means_use_the_default(self):
        self.assertIsNone(_resolve_retention(None))

    def test_zero_is_kept_because_it_means_never_expire(self):
        self.assertEqual(_resolve_retention(0), 0)

    def test_negative_retention_is_rejected(self):
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as caught:
            _resolve_retention(-1)
        self.assertEqual(caught.exception.status_code, 422)


class ChatEndpointTests(unittest.TestCase):
    def _post(self, body):
        with patch(
            "routers.assistant.run_user_agent", AsyncMock(return_value=_run_result())
        ) as run:
            response = _client().post("/api/assistant/chat", json=body)
        return response, run

    def test_blank_query_is_rejected(self):
        response = _client().post("/api/assistant/chat", json={"query": "   "})
        self.assertEqual(response.status_code, 422)

    def test_turn_count_comes_back_incremented(self):
        response, _ = self._post({"query": "q", "user_id": "u1", "turn_count": 4})
        self.assertEqual(response.json()["turn_count"], 5)

    def test_turn_count_defaults_to_a_first_turn(self):
        response, run = self._post({"query": "q", "user_id": "u1"})
        self.assertEqual(run.await_args.kwargs["turn_count"], 0)
        self.assertEqual(response.json()["turn_count"], 1)

    def test_negative_turn_count_is_clamped(self):
        _, run = self._post({"query": "q", "user_id": "u1", "turn_count": -5})
        self.assertEqual(run.await_args.kwargs["turn_count"], 0)

    def test_session_date_is_passed_through_as_a_timestamp(self):
        _, run = self._post(
            {"query": "q", "user_id": "u1", "session_date": "2026-03-14"}
        )
        created_at = run.await_args.kwargs["created_at"]
        self.assertTrue(created_at.startswith("2026-03-14T"))

    def test_malformed_session_date_returns_422(self):
        response = _client().post(
            "/api/assistant/chat",
            json={"query": "q", "user_id": "u1", "session_date": "14/03/2026"},
        )
        self.assertEqual(response.status_code, 422)

    def test_retention_is_passed_through(self):
        _, run = self._post(
            {"query": "q", "user_id": "u1", "session_retention_seconds": 60}
        )
        self.assertEqual(run.await_args.kwargs["retention_seconds"], 60)

    def test_retention_in_force_is_returned_for_the_panel_to_display(self):
        response, _ = self._post({"query": "q", "user_id": "u1"})
        self.assertEqual(response.json()["session_retention_seconds"], 7776000)

    def test_signed_out_shopper_needs_no_controls(self):
        response, run = self._post({"query": "q"})
        self.assertIsNone(run.await_args.kwargs["user_id"])
        self.assertEqual(response.status_code, 200)

    def test_agent_failure_surfaces_as_a_bad_gateway(self):
        with patch(
            "routers.assistant.run_user_agent",
            AsyncMock(side_effect=RuntimeError("boom")),
        ):
            response = _client().post("/api/assistant/chat", json={"query": "q"})
        self.assertEqual(response.status_code, 502)


if __name__ == "__main__":
    unittest.main()
