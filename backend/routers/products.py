from __future__ import annotations

import json
import logging
import os
from typing import Any, Literal

from couchbase.exceptions import CouchbaseException, DocumentNotFoundException
from couchbase.options import QueryOptions, SearchOptions
from couchbase.search import ConjunctionQuery, DisjunctionQuery, MatchQuery, TermQuery
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from models import (
    PaginatedProductSearchResponse,
    PaginatedProductSearchTextResponse,
    PaginatedProductsResponse,
    ProductDetail,
    ProductFacetsResponse,
    ProductSearchResult,
    ProductSearchTextResult,
    ProductSummary,
)
from services import embed_query


logger = logging.getLogger(__name__)


def _require_couchbase(request: Request) -> None:
    """Reject requests while the app runs in degraded mode.

    Startup keeps the API up even when Couchbase is unreachable (see main.py),
    which leaves `app.state.couchbase_*` unset. Without this guard every product
    endpoint would fail with an AttributeError and surface as a 500.

    Degraded mode is recoverable: retry the connection here (rate-limited by
    main._build_reconnector) so a transient outage heals without a restart.
    """
    state = request.app.state
    if not getattr(state, "couchbase_available", False):
        reconnect = getattr(state, "couchbase_reconnect", None)
        if reconnect is not None:
            reconnect()

    if not getattr(state, "couchbase_available", False):
        raise HTTPException(
            status_code=503,
            detail="Couchbase is unavailable; the product catalogue cannot be served.",
        )


router = APIRouter(
    prefix="/api/products",
    tags=["products"],
    dependencies=[Depends(_require_couchbase)],
)

KEY_PREFIX = "product::"

# Fields backing ProductSummary. `name` and `type` are quoted because they are
# awkward as bare identifiers in N1QL paths.
SUMMARY_FIELDS = "p.sku, p.`name`, p.image, p.color, p.category, p.price, p.sizes"

# Document path holding the pre-computed embedding of the descriptive fields,
# and the composite vector index built over it.
VECTOR_FIELD = "descriptive_vectors"
DEFAULT_VECTOR_INDEX = "composite_descriptive_vectors"

# Metrics APPROX_VECTOR_DISTANCE accepts. The value has to match the metric the
# index was created with, otherwise the planner will not use the index.
VECTOR_METRICS = frozenset(
    {"L2", "L2_SQUARED", "EUCLIDEAN", "EUCLIDEAN_SQUARED", "COSINE", "DOT"}
)
DEFAULT_VECTOR_METRIC = "L2_SQUARED"


def _keyspace() -> str:
    bucket_name = os.getenv("COUCHBASE_BUCKET")
    scope_name = os.getenv("COUCHBASE_SCOPE")
    collection_name = os.getenv("COUCHBASE_COLLECTION")
    if not bucket_name or not scope_name or not collection_name:
        raise HTTPException(status_code=500, detail="Couchbase keyspace is not configured")
    return f"`{bucket_name}`.`{scope_name}`.`{collection_name}`"


def _document_key(sku: str) -> str:
    return sku if sku.startswith(KEY_PREFIX) else f"{KEY_PREFIX}{sku}"


def _fetch_documents(collection, keys: list[str]) -> dict[str, dict[str, Any]]:
    """Batch-fetch `keys`, skipping any that are missing or undecodable."""
    if not keys:
        return {}

    multi_result = collection.get_multi(keys)
    documents: dict[str, dict[str, Any]] = {}
    for key in keys:
        get_result = multi_result.results.get(key)
        if not get_result:
            continue

        try:
            documents[key] = get_result.content_as[dict]
        except Exception:
            continue

    return documents


def _build_filters(
    department: str | None,
    product_type: str | None,
    subtype: str | None,
    color: str | None,
    size: str | None,
    min_price: float | None,
    max_price: float | None,
) -> tuple[list[str], dict[str, str | float]]:
    """Translate the listing filters into WHERE clauses and named parameters.

    Shared by the plain listing and the vector search so the sidebar means the
    same thing in both: the composite vector index exists precisely so these
    predicates can narrow a nearest-neighbour scan.
    """
    where_clauses: list[str] = []
    named_parameters: dict[str, str | float] = {}

    if department is not None:
        where_clauses.append("p.category.department = $department")
        named_parameters["department"] = department
    if product_type is not None:
        where_clauses.append("p.category.`type` = $type")
        named_parameters["type"] = product_type
    if subtype is not None:
        where_clauses.append("p.category.subtype = $subtype")
        named_parameters["subtype"] = subtype
    if color is not None:
        where_clauses.append("p.color = $color")
        named_parameters["color"] = color
    if size is not None:
        where_clauses.append("ANY s IN p.sizes SATISFIES s = $size END")
        named_parameters["size"] = size
    if min_price is not None:
        where_clauses.append("p.price.amount >= $minPrice")
        named_parameters["minPrice"] = min_price
    if max_price is not None:
        where_clauses.append("p.price.amount <= $maxPrice")
        named_parameters["maxPrice"] = max_price

    return where_clauses, named_parameters


def _build_text_query(q: str) -> DisjunctionQuery:
    """The keyword-search query, matched against the index's composite `_all`
    field rather than one MatchQuery per field (every indexed field feeds
    `_all` — see scripts/create_indexes.py's `include_in_all`).

    A document matching the whole phrase already qualifies, but one where
    every individual word also matches is a stronger signal, so a conjunction
    of per-word matches competes alongside the phrase match in the outer
    disjunction and outscores partial matches.
    """
    words = q.split()
    return DisjunctionQuery(
        MatchQuery(q, field="_all", analyzer="en"),
        ConjunctionQuery(*(MatchQuery(word, field="_all", analyzer="en") for word in words)),
    )


def _print_vector_query(
    label: str, statement: str, named_parameters: dict[str, Any]
) -> None:
    """Print the SQL++ statement and its bound parameters to the terminal.

    `logger.info` is not guaranteed to reach the terminal (this app configures
    no logging handlers), and seeing exactly what is sent to Couchbase is the
    point of this endpoint for a demo. The embedding is summarised by its
    dimensionality rather than printed in full — it is one float per
    dimension and would otherwise swamp the terminal.
    """
    display_params = dict(named_parameters)
    vector = display_params.get("queryVector")
    if isinstance(vector, list):
        display_params["queryVector"] = f"<{len(vector)}-dim vector>"

    print(f"[vector-search] {label}")
    print(f"[vector-search] SQL++: {statement}")
    print(f"[vector-search] parameters: {display_params}")


def _vector_metric() -> str:
    metric = (os.getenv("COUCHBASE_VECTOR_METRIC") or DEFAULT_VECTOR_METRIC).strip().upper()
    if metric not in VECTOR_METRICS:
        raise HTTPException(
            status_code=500,
            detail=(
                f"COUCHBASE_VECTOR_METRIC='{metric}' is not a supported metric. "
                f"Use one of: {', '.join(sorted(VECTOR_METRICS))}."
            ),
        )
    return metric


def _similarity_score(distance: float, metric: str) -> float:
    """Map a vector distance onto a 0-1 similarity, higher being closer.

    `descriptive_vectors` are unit-normalized, which makes the L2 family exact
    rather than just monotonic: for unit vectors a, b,
        ||a-b||^2 = 2 - 2*cos(a,b)
    so squared distance converts to cosine similarity via `1 - distance/2`
    (and plain L2/EUCLIDEAN via `1 - distance**2/2`). COSINE distance is
    already `1 - cosine_similarity`, so it inverts directly. All three are
    clamped to [0,1] like the COSINE branch always was: cosine similarity can
    go negative, but text embeddings of related items cluster in a narrow
    cone, so a negative score reads as "unrelated" (0) rather than needing the
    [-1,1] range preserved. DOT (a negated inner product, unbounded) is
    squashed into the same range since it has no such closed form.
    """
    if metric in ("L2_SQUARED", "EUCLIDEAN_SQUARED"):
        return max(0.0, min(1.0, 1.0 - distance / 2.0))

    if metric in ("L2", "EUCLIDEAN"):
        return max(0.0, min(1.0, 1.0 - (distance**2) / 2.0))

    if metric == "COSINE":
        return max(0.0, min(1.0, 1.0 - distance))

    inner_product = -distance
    return 0.5 * (1.0 + inner_product / (1.0 + abs(inner_product)))


@router.get("", response_model=PaginatedProductsResponse)
def get_products(
    request: Request,
    department: Literal["Men", "Women"] | None = Query(default=None),
    type: Literal["Tops", "Bottoms", "Activewear", "Footwear"] | None = Query(default=None),
    subtype: str | None = Query(default=None),
    color: str | None = Query(default=None),
    size: str | None = Query(default=None),
    min_price: float | None = Query(default=None, alias="minPrice"),
    max_price: float | None = Query(default=None, alias="maxPrice"),
    sort_by: Literal["name_asc", "name_desc", "price_asc", "price_desc"] = Query(
        default="name_asc", alias="sortBy"
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, alias="pageSize", ge=1),
) -> PaginatedProductsResponse:
    keyspace = _keyspace()
    cluster = request.app.state.couchbase_cluster

    where_clauses, named_parameters = _build_filters(
        department, type, subtype, color, size, min_price, max_price
    )

    # Documents carry no timestamp, so there is no "newest" ordering to offer.
    # `p.sku` is appended as a tiebreaker to keep pagination stable.
    order_by_map = {
        "name_asc": "ORDER BY p.`name` ASC, p.sku ASC",
        "name_desc": "ORDER BY p.`name` DESC, p.sku ASC",
        "price_asc": "ORDER BY p.price.amount ASC, p.sku ASC",
        "price_desc": "ORDER BY p.price.amount DESC, p.sku ASC",
    }
    order_by_clause = order_by_map[sort_by]
    where_statement = f"WHERE {' AND '.join(where_clauses)} " if where_clauses else ""

    items_statement = (
        f"SELECT {SUMMARY_FIELDS} "
        f"FROM {keyspace} AS p "
        f"{where_statement}"
        f"{order_by_clause} "
        "LIMIT $limit OFFSET $offset"
    )
    items_result = cluster.query(
        items_statement,
        QueryOptions(
            named_parameters={
                **named_parameters,
                "limit": page_size,
                "offset": (page - 1) * page_size,
            }
        ),
    )
    items = [ProductSummary.model_validate(row) for row in items_result.rows()]

    count_statement = f"SELECT RAW COUNT(1) FROM {keyspace} AS p {where_statement}".rstrip()
    count_result = cluster.query(
        count_statement,
        QueryOptions(named_parameters=named_parameters),
    )
    total = int(next(iter(count_result.rows()), 0))

    return PaginatedProductsResponse(total=total, page=page, pageSize=page_size, items=items)


@router.get("/facets", response_model=ProductFacetsResponse)
def get_product_facets(
    request: Request,
    department: Literal["Men", "Women"] | None = Query(default=None),
) -> ProductFacetsResponse:
    """Distinct values for every filter the listing page offers.

    Aggregated over the whole (optionally department-scoped) collection, so the
    facet lists never depend on how many products fit on one page.
    """
    keyspace = _keyspace()
    cluster = request.app.state.couchbase_cluster

    named_parameters: dict[str, str] = {}
    where_statement = ""
    if department is not None:
        where_statement = "WHERE p.category.department = $department"
        named_parameters["department"] = department

    # `sizes` is an array per document, so the aggregate is flattened one level
    # before de-duplication.
    statement = (
        "SELECT ARRAY_DISTINCT(ARRAY_AGG(p.category.`type`)) AS types, "
        "ARRAY_DISTINCT(ARRAY_AGG(p.category.subtype)) AS subtypes, "
        "ARRAY_DISTINCT(ARRAY_AGG(p.color)) AS colors, "
        "ARRAY_DISTINCT(ARRAY_FLATTEN(ARRAY_AGG(p.sizes), 1)) AS sizes, "
        "MIN(p.price.amount) AS minPrice, "
        "MAX(p.price.amount) AS maxPrice "
        f"FROM {keyspace} AS p {where_statement}"
    ).rstrip()

    result = cluster.query(statement, QueryOptions(named_parameters=named_parameters))
    # An empty collection still yields one row, but with NULL aggregates.
    row = next(iter(result.rows()), None) or {}

    def _values(key: str) -> list[str]:
        return sorted(value for value in (row.get(key) or []) if isinstance(value, str))

    return ProductFacetsResponse(
        types=_values("types"),
        subtypes=_values("subtypes"),
        colors=_values("colors"),
        sizes=_values("sizes"),
        minPrice=row.get("minPrice") or 0,
        maxPrice=row.get("maxPrice") or 0,
    )


@router.get("/search", response_model=PaginatedProductSearchTextResponse)
def search_products(
    request: Request,
    q: str = Query(min_length=1),
    department: Literal["Men", "Women"] | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, alias="pageSize", ge=1),
) -> PaginatedProductSearchTextResponse:
    if not q.strip():
        raise HTTPException(status_code=422, detail="Search query must not be blank")

    fts_index_name = os.getenv("COUCHBASE_FTS_INDEX")
    if not fts_index_name:
        raise HTTPException(status_code=500, detail="Couchbase FTS index is not configured")

    scope = request.app.state.couchbase_scope
    collection = request.app.state.couchbase_collection

    text_query = _build_text_query(q)

    # The department tab stays visible during a search, so results have to honour
    # it; without this the UI would highlight "Women" over mixed-department hits.
    # `category.department` is indexed as a keyword field (exact terms, not
    # analyzed text), so it's matched with a TermQuery rather than MatchQuery.
    if department is None:
        fts_query = text_query
    else:
        fts_query = ConjunctionQuery(
            text_query,
            TermQuery(department, field="category.department"),
        )

    skip = (page - 1) * page_size
    # Only the document ids are used; the projected fields are re-read from KV
    # below, so there is no reason to have FTS return stored fields as well.
    options = SearchOptions(limit=page_size, skip=skip)

    # Rendered for the UI's query popover, derived from the same query object
    # handed to scope.search() below (via .encodable) so it can never drift
    # from what is actually sent.
    fts_query_json = json.dumps(
        {"query": fts_query.encodable, "size": page_size, "from": skip}, indent=2
    )

    result = scope.search(fts_index_name, fts_query, options)

    hits = list(result.rows())
    metrics = result.metadata().metrics()
    total_rows = getattr(metrics, "total_rows", 0)
    total = int(total_rows() if callable(total_rows) else total_rows)

    if not hits:
        return PaginatedProductSearchTextResponse(
            total=0, page=page, pageSize=page_size, items=[], ftsQuery=fts_query_json
        )

    # seed_data.py writes every document under `product::<sku>` and
    # _document_key is idempotent, so one key per hit resolves the normal case.
    keys: list[str] = []
    for hit in hits:
        key = _document_key(hit.id)
        if key not in keys:
            keys.append(key)

    documents = _fetch_documents(collection, keys)

    # Tolerate an index whose ids are stored without the prefix: only the hits
    # that actually missed need a second lookup.
    retry_keys = list(
        dict.fromkeys(
            hit.id
            for hit in hits
            if _document_key(hit.id) not in documents and hit.id not in documents
        )
    )
    if retry_keys:
        documents.update(_fetch_documents(collection, retry_keys))

    items: list[ProductSearchTextResult] = []
    for hit in hits:
        document = documents.get(_document_key(hit.id)) or documents.get(hit.id)
        if document is None:
            continue

        items.append(
            ProductSearchTextResult.model_validate({**document, "score": round(hit.score, 4)})
        )

    # `total` is the FTS match count. A hit whose document no longer exists in
    # KV means the index is lagging behind the collection, which would otherwise
    # silently show up as a short page.
    unresolved = len(hits) - len(items)
    if unresolved:
        logger.warning(
            "%d of %d search hits could not be loaded from KV; the FTS index '%s' "
            "may be stale, so `total` (%d) overstates the retrievable results.",
            unresolved,
            len(hits),
            fts_index_name,
            total,
        )

    return PaginatedProductSearchTextResponse(
        total=total, page=page, pageSize=page_size, items=items, ftsQuery=fts_query_json
    )


@router.get("/vector-search", response_model=PaginatedProductSearchResponse)
def vector_search_products(
    request: Request,
    q: str = Query(min_length=1),
    department: Literal["Men", "Women"] | None = Query(default=None),
    type: Literal["Tops", "Bottoms", "Activewear", "Footwear"] | None = Query(default=None),
    subtype: str | None = Query(default=None),
    color: str | None = Query(default=None),
    size: str | None = Query(default=None),
    min_price: float | None = Query(default=None, alias="minPrice"),
    max_price: float | None = Query(default=None, alias="maxPrice"),
    top_k: int = Query(default=10, alias="topK", ge=1, le=20),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, alias="pageSize", ge=1),
) -> PaginatedProductSearchResponse:
    """Nearest-neighbour product search over a natural-language description.

    `q` is embedded by the Capella-hosted model and handed to SQL++ as a query
    parameter, so the whole ranking happens in Couchbase through the composite
    vector index. The sidebar filters ride along as ordinary predicates.
    """
    if not q.strip():
        raise HTTPException(status_code=422, detail="Search query must not be blank")

    keyspace = _keyspace()
    cluster = request.app.state.couchbase_cluster
    index_name = os.getenv("COUCHBASE_VECTOR_INDEX") or DEFAULT_VECTOR_INDEX
    metric = _vector_metric()

    query_vector = embed_query(q)

    where_clauses, named_parameters = _build_filters(
        department, type, subtype, color, size, min_price, max_price
    )
    where_statement = f"WHERE {' AND '.join(where_clauses)}\n" if where_clauses else ""

    # The metric is interpolated rather than parameterised: the planner has to
    # see it as a literal to match it against the index. _vector_metric() has
    # already checked it against a fixed allow-list.
    distance_expression = f'APPROX_VECTOR_DISTANCE(p.{VECTOR_FIELD}, $queryVector, "{metric}")'

    # ORDER BY repeats the full expression instead of the `distance` alias:
    # pushing the scan down into the vector index requires the ordering term to
    # be the APPROX_VECTOR_DISTANCE call itself. Laid out one clause per line so
    # it reads well both in the terminal log and in the UI's query popover.
    def _statement(index_hint: str) -> str:
        return (
            f"SELECT {SUMMARY_FIELDS}, {distance_expression} AS distance\n"
            f"FROM {keyspace} AS p{index_hint}\n"
            f"{where_statement}"
            f"ORDER BY {distance_expression}\n"
            "LIMIT $topK"
        )

    vector_params: dict[str, Any] = {
        **named_parameters,
        "queryVector": query_vector,
        "topK": top_k,
    }

    # A fresh QueryOptions per attempt: the SDK consumes the object when it turns
    # it into a request, so the retry below cannot share one.
    def _options() -> QueryOptions:
        return QueryOptions(named_parameters=dict(vector_params))

    hinted_statement = _statement(f" USE INDEX (`{index_name}` USING GSI)")
    executed_statement = hinted_statement
    _print_vector_query(
        "Sending vector search query to Couchbase (with index hint):",
        hinted_statement,
        vector_params,
    )
    try:
        rows = list(cluster.query(hinted_statement, _options()).rows())
    except CouchbaseException as exc:
        # A forced index fails outright when it cannot serve the statement — a
        # composite index whose leading key is not among the active filters, for
        # instance. Let the planner pick instead of failing the whole request.
        print(
            f"[vector-search] WARNING: query with USE INDEX (`{index_name}`) failed "
            f"({exc}); retrying without the hint."
        )
        logger.warning(
            "Vector query with USE INDEX (`%s`) failed; retrying without the hint.",
            index_name,
            exc_info=True,
        )
        fallback_statement = _statement("")
        executed_statement = fallback_statement
        _print_vector_query(
            "Retrying vector search query without the index hint:",
            fallback_statement,
            vector_params,
        )
        try:
            rows = list(cluster.query(fallback_statement, _options()).rows())
        except CouchbaseException as retry_exc:
            detail = (
                f"The vector search query failed: {retry_exc}. Check that the "
                f"'{index_name}' index exists over `{VECTOR_FIELD}` and was built "
                f"with the {metric} metric (COUCHBASE_VECTOR_METRIC)."
            )
            print(f"[vector-search] ERROR: {detail}")
            logger.exception("Vector search query failed.")
            raise HTTPException(status_code=502, detail=detail) from retry_exc

    results: list[ProductSearchResult] = []
    for row in rows:
        distance = row.pop("distance", None)
        if distance is None:
            # A document without an embedding cannot be scored; ranking it
            # alongside real hits would be meaningless.
            continue

        distance = float(distance)
        results.append(
            ProductSearchResult.model_validate(
                {
                    **row,
                    "distance": distance,
                    "score": round(_similarity_score(distance, metric), 4),
                }
            )
        )

    # `top_k` bounds the whole result set, so pagination slices what the one
    # nearest-neighbour scan returned. `total` therefore stays stable across page
    # turns instead of growing with the offset.
    start = (page - 1) * page_size
    return PaginatedProductSearchResponse(
        total=len(results),
        page=page,
        pageSize=page_size,
        items=results[start : start + page_size],
        sqlQuery=executed_statement,
    )


@router.get("/{sku}", response_model=ProductDetail)
def get_product_by_sku(request: Request, sku: str) -> ProductDetail:
    collection = request.app.state.couchbase_collection

    try:
        result = collection.get(_document_key(sku))
    except (DocumentNotFoundException, KeyError):
        raise HTTPException(status_code=404, detail="Product not found")
    except CouchbaseException as exc:
        # Anything other than "not found" — a KV timeout, a dropped connection —
        # would otherwise escape uncaught and crash the ASGI app with a raw 500.
        detail = (
            f"Could not read product '{sku}' from Couchbase: {exc}. "
            "The cluster may be temporarily unreachable; retrying may succeed."
        )
        print(f"[products] ERROR: {detail}")
        logger.exception("KV get failed for sku=%s", sku)
        raise HTTPException(status_code=503, detail=detail) from exc

    return ProductDetail.model_validate(result.content_as[dict])
