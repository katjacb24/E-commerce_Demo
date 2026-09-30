from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Ensure imports work when running: python backend/scripts/create_indexes.py
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from couchbase.exceptions import CouchbaseException
from couchbase.management.search import SearchIndex

from db.connection import initialize_couchbase, shutdown_couchbase


# Secondary indexes backing the filters exposed by GET /api/products.
# The primary index covers unfiltered listings, the GET /api/products/facets
# aggregates, and the `size` filter, which has no dedicated index.
GSI_INDEXES: list[tuple[str, str]] = [
    ("idx_products_primary", "PRIMARY"),
    ("idx_products_department", "category.department"),
    ("idx_products_type", "category.`type`"),
    ("idx_products_subtype", "category.subtype"),
    ("idx_products_color", "color"),
    ("idx_products_price", "price.amount"),
    ("idx_products_name", "`name`"),
]

# Only these document paths are searchable through FTS; everything else is
# excluded so the index stays small. Each is indexed as text with the English
# analyzer and folded into _all, matching the analyzer the
# /api/products/search MatchQueries use. `category` is an object, so its
# leaves are mapped individually.
FTS_TEXT_FIELDS: list[str] = [
    "category.type",
    "category.subtype",
    "color",
    "description",
    "material",
    "name",
    "tags",
]

# Indexed as text with the keyword analyzer, so the whole value stays a single
# token and department terms match exactly rather than being stemmed. Kept out
# of _all so free-text queries don't hit it.
FTS_KEYWORD_FIELDS: list[str] = [
    "category.department",
]


def _build_fts_properties(
    text_paths: list[str], keyword_paths: list[str]
) -> dict:
    """Turn dotted document paths into a nested FTS property mapping.

    Intermediate segments become object mappings; the leaf carries the text
    field definition. FTS names a leaf field by its own segment, and the query
    side addresses it by the full dotted path.
    """
    properties: dict = {}
    specs = [(path, "en", True) for path in text_paths]
    specs += [(path, "keyword", False) for path in keyword_paths]

    for path, analyzer, include_in_all in specs:
        *parents, leaf = path.split(".")
        node = properties
        for segment in parents:
            child = node.setdefault(
                segment, {"dynamic": False, "enabled": True, "properties": {}}
            )
            node = child["properties"]

        node[leaf] = {
            "dynamic": False,
            "enabled": True,
            "fields": [
                {
                    "analyzer": analyzer,
                    "include_in_all": include_in_all,
                    "index": True,
                    "name": leaf,
                    "type": "text",
                }
            ],
        }
    return properties


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def create_gsi_indexes(cluster, keyspace: str) -> None:
    for index_name, expression in GSI_INDEXES:
        if expression == "PRIMARY":
            statement = f"CREATE PRIMARY INDEX `{index_name}` IF NOT EXISTS ON {keyspace}"
        else:
            statement = f"CREATE INDEX `{index_name}` IF NOT EXISTS ON {keyspace}({expression})"

        try:
            list(cluster.query(statement).rows())
            print(f"  GSI  {index_name}: ok")
        except CouchbaseException as exc:
            print(f"  GSI  {index_name}: FAILED ({type(exc).__name__})")
            raise


def create_fts_index(scope, bucket_name: str, scope_name: str, collection_name: str) -> None:
    index_name = os.getenv("COUCHBASE_FTS_INDEX") or "products_search"
    if "." in index_name:
        raise RuntimeError(
            f"COUCHBASE_FTS_INDEX must be a scope-relative name (got '{index_name}'). "
            "scope.search() resolves names within the configured scope."
        )

    manager = scope.search_indexes()
    if any(existing.name == index_name for existing in manager.get_all_indexes()):
        print(f"  FTS  {index_name}: already exists, left unchanged")
        return

    # Explicit mapping over the products collection: FTS_TEXT_FIELDS are
    # indexed with the English analyzer, so the name/description/tags/color/
    # material match queries in the search endpoint all resolve, and
    # FTS_KEYWORD_FIELDS are indexed verbatim for exact-term matching.
    properties = _build_fts_properties(FTS_TEXT_FIELDS, FTS_KEYWORD_FIELDS)

    manager.upsert_index(
        SearchIndex(
            name=index_name,
            source_name=bucket_name,
            source_type="couchbase",
            idx_type="fulltext-index",
            params={
                "doc_config": {
                    "mode": "scope.collection.type_field",
                    "type_field": "type",
                },
                "mapping": {
                    "default_analyzer": "en",
                    "default_datetime_parser": "dateTimeOptional",
                    "default_field": "_all",
                    "default_mapping": {"dynamic": False, "enabled": False},
                    "default_type": "_default",
                    "docvalues_dynamic": False,
                    "index_dynamic": False,
                    "store_dynamic": False,
                    "type_field": "_type",
                    "types": {
                        f"{scope_name}.{collection_name}": {
                            "dynamic": False,
                            "enabled": True,
                            "properties": properties,
                        }
                    },
                },
                "store": {"indexType": "scorch", "segmentVersion": 16},
            },
        )
    )
    print(f"  FTS  {index_name}: created")


def create_indexes() -> None:
    load_dotenv(dotenv_path=BACKEND_DIR / ".env", override=False)

    cluster, _, scope, _ = initialize_couchbase()
    bucket_name = _required_env("COUCHBASE_BUCKET")
    scope_name = _required_env("COUCHBASE_SCOPE")
    collection_name = _required_env("COUCHBASE_COLLECTION")
    keyspace = f"`{bucket_name}`.`{scope_name}`.`{collection_name}`"

    try:
        print(f"Creating indexes on {keyspace}")
        create_gsi_indexes(cluster, keyspace)
        create_fts_index(scope, bucket_name, scope_name, collection_name)
    finally:
        shutdown_couchbase(cluster)

    print("Done. FTS indexing runs in the background; search may lag for a few seconds.")


if __name__ == "__main__":
    create_indexes()
