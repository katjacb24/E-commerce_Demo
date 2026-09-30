from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Ensure imports work when running: python backend/scripts/seed_data.py
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from db.connection import initialize_couchbase, shutdown_couchbase


SEED_FILE = BACKEND_DIR / "seed_data" / "products.json"
KEY_PREFIX = "product::"


def load_products(seed_file: Path = SEED_FILE) -> list[dict[str, Any]]:
    if not seed_file.is_file():
        raise RuntimeError(f"Seed file not found: {seed_file}")

    with seed_file.open(encoding="utf-8") as handle:
        documents = json.load(handle)

    if not isinstance(documents, list):
        raise RuntimeError(f"Expected a JSON array of documents in {seed_file}")

    return documents


def document_key(document: dict[str, Any], index: int) -> str:
    sku = document.get("sku")
    if isinstance(sku, str) and sku.strip():
        return f"{KEY_PREFIX}{sku.strip()}"
    raise RuntimeError(f"Document at index {index} has no usable 'sku' field for the document key")


def build_documents(seed_file: Path = SEED_FILE) -> list[tuple[str, dict[str, Any]]]:
    documents: list[tuple[str, dict[str, Any]]] = []
    seen_keys: set[str] = set()

    for index, document in enumerate(load_products(seed_file)):
        if not isinstance(document, dict):
            raise RuntimeError(f"Document at index {index} is not a JSON object")

        key = document_key(document, index)
        if key in seen_keys:
            raise RuntimeError(f"Duplicate document key '{key}' at index {index}")
        seen_keys.add(key)

        documents.append((key, document))

    return documents


def seed_products() -> None:
    # The GSI and FTS indexes these documents are queried through are created by
    # scripts/create_indexes.py; run it once after seeding.
    load_dotenv(dotenv_path=BACKEND_DIR / ".env", override=False)

    documents = build_documents()
    cluster, _, _, collection = initialize_couchbase()

    try:
        for key, document in documents:
            collection.upsert(key, document)
    finally:
        shutdown_couchbase(cluster)

    print(f"Upserted {len(documents)} product documents from {SEED_FILE}.")


if __name__ == "__main__":
    seed_products()
