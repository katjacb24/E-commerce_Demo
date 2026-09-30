from __future__ import annotations

import base64
import logging
import os
from functools import lru_cache
from typing import Any, NoReturn

import httpx
from fastapi import HTTPException


logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 20.0


def _raise(status_code: int, detail: str, exc: Exception | None = None) -> NoReturn:
    """Surface a failure both to the terminal and to the API caller.

    `logger.error` alone is not guaranteed to reach the terminal (this app
    configures no logging handlers), so the message is also printed directly.
    """
    print(f"[embeddings] ERROR: {detail}")
    logger.error(detail)
    raise HTTPException(status_code=status_code, detail=detail) from exc


# Identical queries are re-embedded whenever the listing page re-renders (a page
# turn, a filter click), so the last few vectors are kept. The cache key carries
# the model and input type: changing either in .env must not serve a vector
# produced by the previous configuration.
CACHE_SIZE = 256


def _endpoint_url() -> str:
    """Resolve the Capella Model Service embeddings URL.

    Accepts the bare endpoint host, the `/v1` root, or the full
    `/v1/embeddings` path, because Capella surfaces the endpoint in all three
    shapes depending on where it is copied from.
    """
    base = (os.getenv("CAPELLA_AI_ENDPOINT") or "").strip().rstrip("/")
    if not base:
        _raise(
            500,
            "CAPELLA_AI_ENDPOINT is not configured; natural-language search is unavailable. "
            "Set it in backend/.env to the Capella AI Services (Model Service) endpoint.",
        )

    if base.endswith("/embeddings"):
        return base
    if base.endswith("/v1"):
        return f"{base}/embeddings"
    return f"{base}/v1/embeddings"


def _auth_header() -> dict[str, str]:
    """Bearer token if one is configured, otherwise the cluster credentials.

    Capella AI endpoints accept an API key as a bearer token; deployments that
    reuse the database user for the Model Service authenticate with Basic auth
    instead, so both are supported without extra configuration.
    """
    api_key = (os.getenv("CAPELLA_AI_API_KEY") or "").strip()
    if api_key:
        return {"Authorization": f"Bearer {api_key}"}

    username = os.getenv("COUCHBASE_USERNAME")
    password = os.getenv("COUCHBASE_PASSWORD")
    if username and password:
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        return {"Authorization": f"Basic {token}"}

    _raise(
        500,
        "No credentials for the Capella embedding model. Set CAPELLA_AI_API_KEY, or "
        "COUCHBASE_USERNAME/COUCHBASE_PASSWORD if the Model Service reuses the "
        "database user.",
    )


def _timeout_seconds() -> float:
    raw = os.getenv("CAPELLA_AI_TIMEOUT_SECONDS")
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        return float(raw)
    except ValueError:
        logger.warning(
            "CAPELLA_AI_TIMEOUT_SECONDS=%r is not a number; using %.1fs.",
            raw,
            DEFAULT_TIMEOUT_SECONDS,
        )
        return DEFAULT_TIMEOUT_SECONDS


def _extract_vector(body: Any) -> list[float]:
    """Pull the embedding out of an OpenAI-compatible response body.

    Capella's Model Service mirrors the OpenAI schema (`data[0].embedding`);
    the flatter `embeddings`/`embedding` shapes are accepted as well so a model
    that returns them does not need a code change.
    """
    if isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, dict) and isinstance(first.get("embedding"), list):
                return [float(value) for value in first["embedding"]]

        embeddings = body.get("embeddings")
        if isinstance(embeddings, list) and embeddings and isinstance(embeddings[0], list):
            return [float(value) for value in embeddings[0]]

        embedding = body.get("embedding")
        if isinstance(embedding, list):
            return [float(value) for value in embedding]

    _raise(
        502,
        f"The Capella embedding model returned an unrecognised response shape: "
        f"{str(body)[:500]}",
    )


@lru_cache(maxsize=CACHE_SIZE)
def _embed_cached(model: str, input_type: str | None, text: str) -> tuple[float, ...]:
    payload: dict[str, Any] = {"model": model, "input": [text]}
    if input_type:
        # Asymmetric retrieval models (e.g. NVIDIA embedqa) embed a question and
        # a document differently and reject a request that omits this.
        payload["input_type"] = input_type

    url = _endpoint_url()
    headers = {"Content-Type": "application/json", **_auth_header()}

    timeout = _timeout_seconds()
    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=timeout)
        response.raise_for_status()
        body = response.json()
    except httpx.ConnectError as exc:
        # DNS failure, refused connection, TLS handshake failure, etc. — the
        # request never reached the server, which is the case the user asked
        # to have called out explicitly rather than folded into a generic
        # "unreachable" message.
        _raise(
            502,
            f"Could not establish a connection to the Capella embedding model at "
            f"{url}. Check CAPELLA_AI_ENDPOINT and that the endpoint is reachable "
            f"from this machine (network/VPN/firewall). Underlying error: {exc}",
            exc,
        )
    except httpx.TimeoutException as exc:
        _raise(
            502,
            f"The Capella embedding model at {url} did not respond within "
            f"{timeout:.1f}s. It may be cold-starting or overloaded; increase "
            f"CAPELLA_AI_TIMEOUT_SECONDS or retry.",
            exc,
        )
    except httpx.HTTPStatusError as exc:
        body_preview = exc.response.text[:500]
        _raise(
            502,
            f"The Capella embedding model at {url} rejected the request with "
            f"HTTP {exc.response.status_code}. Check CAPELLA_EMBEDDING_MODEL and "
            f"CAPELLA_AI_API_KEY. Response: {body_preview}",
            exc,
        )
    except httpx.HTTPError as exc:
        _raise(
            502,
            f"A network error occurred while calling the Capella embedding model at "
            f"{url}: {exc}",
            exc,
        )

    vector = _extract_vector(body)
    if not vector:
        _raise(
            502,
            f"The Capella embedding model at {url} returned an empty vector for "
            f"model '{model}'.",
        )

    # lru_cache hands the same object to every caller, so the vector is frozen
    # here and copied at the call site.
    return tuple(vector)


def embed_query(text: str) -> list[float]:
    """Embed a natural-language product query with the Capella-hosted model.

    The model must be the one that produced the `descriptive_vectors` field on
    the product documents: a query vector from a different model has neither the
    right dimensionality nor a comparable geometry.
    """
    model = (os.getenv("CAPELLA_EMBEDDING_MODEL") or "").strip()
    if not model:
        _raise(
            500,
            "CAPELLA_EMBEDDING_MODEL is not configured; natural-language search is "
            "unavailable. Set it in backend/.env to the model that produced "
            "descriptive_vectors.",
        )

    input_type = (os.getenv("CAPELLA_EMBEDDING_INPUT_TYPE") or "").strip() or None
    return list(_embed_cached(model, input_type, text.strip()))
