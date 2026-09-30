from __future__ import annotations

import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import httpx
from fastapi import HTTPException

from services.embeddings import _embed_cached, embed_query


class EmbeddingErrorMessageTests(unittest.TestCase):
    """Every failure mode must raise a specific, actionable HTTPException and
    print to the terminal — a silent generic 502 is what this module exists to
    avoid."""

    def setUp(self):
        os.environ["CAPELLA_AI_ENDPOINT"] = "https://ai.example.cloud.couchbase.com"
        os.environ["CAPELLA_AI_API_KEY"] = "test-key"
        os.environ["CAPELLA_EMBEDDING_MODEL"] = "test-model"
        os.environ.pop("CAPELLA_EMBEDDING_INPUT_TYPE", None)
        os.environ.pop("CAPELLA_AI_TIMEOUT_SECONDS", None)
        _embed_cached.cache_clear()

    def tearDown(self):
        _embed_cached.cache_clear()

    def _embed_with_captured_output(self, text: str = "a floral summer dress"):
        captured = io.StringIO()
        with redirect_stdout(captured):
            with self.assertRaises(HTTPException) as ctx:
                embed_query(text)
        return ctx.exception, captured.getvalue()

    def test_connection_error_names_the_endpoint_and_cause(self):
        with patch(
            "services.embeddings.httpx.post",
            side_effect=httpx.ConnectError("Connection refused"),
        ):
            exc, output = self._embed_with_captured_output()

        self.assertEqual(exc.status_code, 502)
        self.assertIn("Could not establish a connection", exc.detail)
        self.assertIn("ai.example.cloud.couchbase.com", exc.detail)
        self.assertIn("Connection refused", exc.detail)
        # Printed for terminal visibility, since no logging handler is configured.
        self.assertIn("[embeddings] ERROR", output)
        self.assertIn("Could not establish a connection", output)

    def test_timeout_names_the_configured_timeout(self):
        os.environ["CAPELLA_AI_TIMEOUT_SECONDS"] = "7"
        with patch(
            "services.embeddings.httpx.post",
            side_effect=httpx.ConnectTimeout("timed out"),
        ):
            exc, output = self._embed_with_captured_output()

        self.assertEqual(exc.status_code, 502)
        self.assertIn("7.0s", exc.detail)
        self.assertIn("CAPELLA_AI_TIMEOUT_SECONDS", exc.detail)
        self.assertIn("[embeddings] ERROR", output)

    def test_http_status_error_includes_status_and_body(self):
        request = httpx.Request("POST", "https://ai.example.cloud.couchbase.com/v1/embeddings")
        response = httpx.Response(401, request=request, text="unauthorized")

        with patch(
            "services.embeddings.httpx.post",
            side_effect=httpx.HTTPStatusError(
                "unauthorized", request=request, response=response
            ),
        ):
            exc, output = self._embed_with_captured_output()

        self.assertEqual(exc.status_code, 502)
        self.assertIn("HTTP 401", exc.detail)
        self.assertIn("unauthorized", exc.detail)
        self.assertIn("CAPELLA_AI_API_KEY", exc.detail)
        self.assertIn("[embeddings] ERROR", output)

    def test_missing_endpoint_is_a_config_error(self):
        os.environ.pop("CAPELLA_AI_ENDPOINT", None)

        exc, output = self._embed_with_captured_output()

        self.assertEqual(exc.status_code, 500)
        self.assertIn("CAPELLA_AI_ENDPOINT", exc.detail)
        self.assertIn("[embeddings] ERROR", output)

    def test_missing_model_is_a_config_error(self):
        os.environ.pop("CAPELLA_EMBEDDING_MODEL", None)

        exc, output = self._embed_with_captured_output()

        self.assertEqual(exc.status_code, 500)
        self.assertIn("CAPELLA_EMBEDDING_MODEL", exc.detail)

    def test_missing_credentials_is_a_config_error(self):
        os.environ.pop("CAPELLA_AI_API_KEY", None)
        os.environ.pop("COUCHBASE_USERNAME", None)
        os.environ.pop("COUCHBASE_PASSWORD", None)

        exc, output = self._embed_with_captured_output()

        self.assertEqual(exc.status_code, 500)
        self.assertIn("CAPELLA_AI_API_KEY", exc.detail)

    def test_unrecognised_response_shape_is_reported(self):
        request = httpx.Request("POST", "https://ai.example.cloud.couchbase.com/v1/embeddings")
        response = httpx.Response(200, request=request, json={"unexpected": "shape"})

        with patch("services.embeddings.httpx.post", return_value=response):
            exc, output = self._embed_with_captured_output()

        self.assertEqual(exc.status_code, 502)
        self.assertIn("unrecognised response shape", exc.detail)
        self.assertIn("[embeddings] ERROR", output)


if __name__ == "__main__":
    unittest.main()
