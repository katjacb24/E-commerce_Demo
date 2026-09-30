from __future__ import annotations

import io
import os
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from couchbase.exceptions import CouchbaseException, DocumentNotFoundException
from couchbase.search import ConjunctionQuery, DisjunctionQuery
from fastapi.testclient import TestClient


# Both fixtures below are verbatim copies of documents in
# backend/seed_data/products.json; keep them in sync with that file.
_PRODUCT_DOC = {
    "image": "39773.jpg",
    "sku": "SHIRT-STR-NVY-001",
    "name": "Vertical Stripe Long-Sleeve Shirt",
    "description": (
        "Men's long-sleeve casual shirt in navy, pink and light-blue vertical stripes "
        "with a button-down collar and chest pocket; sleeves rolled up."
    ),
    "category": {"department": "Men", "type": "Tops", "subtype": "Shirts"},
    "color": "navy",
    "material": "100% cotton",
    "sizes": ["S", "M", "L", "XL"],
    "price": {"amount": 49.0, "currency": "EUR"},
    "tags": ["casual", "striped", "long-sleeve", "navy", "button-down", "multi-color"],
    "stock": 40,
}

# The listing query projects only the ProductSummary fields.
_SUMMARY_ROW = {
    "sku": _PRODUCT_DOC["sku"],
    "name": _PRODUCT_DOC["name"],
    "image": _PRODUCT_DOC["image"],
    "color": _PRODUCT_DOC["color"],
    "category": _PRODUCT_DOC["category"],
    "price": _PRODUCT_DOC["price"],
    "sizes": _PRODUCT_DOC["sizes"],
}

_SEARCH_DOC = {
    "image": "39806.jpg",
    "sku": "TROUSER-CHN-BLK-001",
    "name": "Black Flat-Front Chinos",
    "description": (
        "Men's straight-leg chino trousers in classic black with a flat front and "
        "zip fly, ideal for smart-casual wear."
    ),
    "category": {"department": "Men", "type": "Bottoms", "subtype": "Chinos"},
    "color": "black",
    "material": "98% cotton, 2% elastane",
    "sizes": ["28", "30", "32", "34", "36"],
    "price": {"amount": 59.0, "currency": "EUR"},
    "tags": ["casual", "chino", "flat-front", "straight-leg", "black", "smart-casual"],
    "stock": 35,
}


class _FakeQueryResult:
    def __init__(self, rows):
        self._rows = rows

    def rows(self):
        return iter(self._rows)


# One row of aggregates, mirroring what the /facets SELECT projects.
_FACETS_ROW = {
    "types": ["Tops", "Bottoms"],
    "subtypes": ["Shirts", "Chinos"],
    "colors": ["navy", "black"],
    "sizes": ["S", "M", "L", "XL", "30", "32"],
    "minPrice": 15.0,
    "maxPrice": 99.0,
}


# The vector query projects the summary fields plus the computed distance.
_VECTOR_ROW = {**_SUMMARY_ROW, "distance": 0.25}

# Stands in for whatever the Capella embedding model returns; only its identity
# matters to the assertions, not its dimensionality.
_QUERY_VECTOR = [0.1, 0.2, 0.3]


class _FakeCluster:
    def __init__(self):
        self.calls = []
        self.options = []

    def query(self, statement, options=None):
        self.calls.append(statement)
        self.options.append(options)

        if "ARRAY_DISTINCT" in statement:
            return _FakeQueryResult([_FACETS_ROW])

        if "APPROX_VECTOR_DISTANCE" in statement:
            return _FakeQueryResult([dict(_VECTOR_ROW)])

        if "COUNT" in statement:
            # A filtered listing reports a smaller total than the full collection.
            if "WHERE" in statement:
                return _FakeQueryResult([7])
            return _FakeQueryResult([42])

        return _FakeQueryResult([_SUMMARY_ROW])


# ---------------------------------------------------------------------------
# FTS search fakes
# ---------------------------------------------------------------------------


class _FakeSearchHit:
    def __init__(self, doc_id: str, score: float = 1.23):
        self.id = doc_id
        self.score = score


class _FakeSearchMetrics:
    def total_rows(self) -> int:
        return 1


class _FakeSearchMetadata:
    def metrics(self) -> _FakeSearchMetrics:
        return _FakeSearchMetrics()


class _FakeSearchResult:
    def __init__(self, hits: list[_FakeSearchHit]):
        self._hits = hits

    def rows(self):
        return iter(self._hits)

    def metadata(self) -> _FakeSearchMetadata:
        return _FakeSearchMetadata()


class _FakeGetResult:
    def __init__(self, doc: dict):
        self.success = True
        self.content_as = {dict: doc}


class _FakeMultiResult:
    def __init__(self, docs: dict[str, dict]):
        self.results = {key: _FakeGetResult(doc) for key, doc in docs.items()}


class _FakeScope:
    def __init__(self):
        self.last_index_name: str | None = None
        self.last_query = None

    def search(self, index_name: str, query, options=None) -> _FakeSearchResult:
        self.last_index_name = index_name
        self.last_query = query
        return _FakeSearchResult([_FakeSearchHit(f"product::{_SEARCH_DOC['sku']}")])


class _FakeCollection:
    """Keyed by `product::<sku>`, matching how seed_data.py writes documents."""

    def __init__(self):
        self.docs = {
            f"product::{_PRODUCT_DOC['sku']}": _PRODUCT_DOC,
            f"product::{_SEARCH_DOC['sku']}": _SEARCH_DOC,
        }

    def get(self, key: str) -> _FakeGetResult:
        if key not in self.docs:
            raise DocumentNotFoundException(message=f"missing key: {key}")
        return _FakeGetResult(self.docs[key])

    def get_multi(self, keys: list[str]) -> _FakeMultiResult:
        return _FakeMultiResult({k: self.docs[k] for k in keys if k in self.docs})


class ProductsApiTests(unittest.TestCase):
    @staticmethod
    def _build_client():
        os.environ["COUCHBASE_BUCKET"] = "retail"
        os.environ["COUCHBASE_SCOPE"] = "retail-scope"
        os.environ["COUCHBASE_COLLECTION"] = "products"

        fake_cluster = _FakeCluster()
        fake_bucket = SimpleNamespace()
        fake_scope = SimpleNamespace()
        fake_collection = _FakeCollection()

        patchers = (
            patch(
                "main.initialize_couchbase",
                return_value=(fake_cluster, fake_bucket, fake_scope, fake_collection),
            ),
            patch("main.shutdown_couchbase", return_value=None),
        )
        return fake_cluster, patchers

    @staticmethod
    def _build_search_client():
        os.environ["COUCHBASE_BUCKET"] = "retail"
        os.environ["COUCHBASE_SCOPE"] = "retail-scope"
        os.environ["COUCHBASE_COLLECTION"] = "products"
        # Scope-relative name: scope.search() resolves it within the configured scope.
        os.environ["COUCHBASE_FTS_INDEX"] = "products_search"

        fake_cluster = _FakeCluster()
        fake_bucket = SimpleNamespace()
        fake_scope = _FakeScope()
        fake_collection = _FakeCollection()

        patchers = (
            patch(
                "main.initialize_couchbase",
                return_value=(fake_cluster, fake_bucket, fake_scope, fake_collection),
            ),
            patch("main.shutdown_couchbase", return_value=None),
        )
        return patchers, fake_scope

    @staticmethod
    def _build_vector_client():
        os.environ["COUCHBASE_BUCKET"] = "retail"
        os.environ["COUCHBASE_SCOPE"] = "retail-scope"
        os.environ["COUCHBASE_COLLECTION"] = "products"
        os.environ["COUCHBASE_VECTOR_INDEX"] = "composite_descriptive_vectors"
        # setdefault, not assignment: the metric tests below set this themselves
        # before calling in, and must not have it overwritten from under them.
        os.environ.setdefault("COUCHBASE_VECTOR_METRIC", "L2_SQUARED")

        fake_cluster = _FakeCluster()
        fake_bucket = SimpleNamespace()
        fake_scope = SimpleNamespace()
        fake_collection = _FakeCollection()

        patchers = (
            patch(
                "main.initialize_couchbase",
                return_value=(fake_cluster, fake_bucket, fake_scope, fake_collection),
            ),
            patch("main.shutdown_couchbase", return_value=None),
            # The embedding model is a remote Capella endpoint; the suite must
            # stay runnable without one.
            patch("routers.products.embed_query", return_value=_QUERY_VECTOR),
        )
        return fake_cluster, patchers

    def _vector_get(self, params: dict | None = None):
        fake_cluster, patchers = self._build_vector_client()
        with patchers[0], patchers[1], patchers[2] as embed:
            from main import app

            with TestClient(app) as client:
                response = client.get("/api/products/vector-search", params=params or {})
        return response, fake_cluster, embed

    def _get(self, params: dict | None = None):
        fake_cluster, patchers = self._build_client()
        with patchers[0], patchers[1]:
            from main import app

            with TestClient(app) as client:
                response = client.get("/api/products", params=params or {})
        return response, fake_cluster

    def _search_get(self, path: str, params: dict | None = None):
        patchers, fake_scope = self._build_search_client()
        with patchers[0], patchers[1]:
            from main import app

            with TestClient(app) as client:
                response = client.get(path, params=params or {})
        return response, fake_scope

    # ------------------------------------------------------------------
    # Listing endpoint
    # ------------------------------------------------------------------

    def test_get_products_returns_paginated_response(self):
        response, _ = self._get()

        self.assertEqual(response.status_code, 200)
        body = response.json()

        self.assertIn("total", body)
        self.assertIn("page", body)
        self.assertIn("pageSize", body)
        self.assertIn("items", body)
        self.assertGreater(len(body["items"]), 0)

    def test_summary_items_expose_new_schema_fields(self):
        response, _ = self._get()

        item = response.json()["items"][0]
        self.assertEqual(item["sku"], "SHIRT-STR-NVY-001")
        self.assertEqual(item["name"], "Vertical Stripe Long-Sleeve Shirt")
        self.assertEqual(item["category"]["department"], "Men")
        self.assertEqual(item["category"]["type"], "Tops")
        self.assertEqual(item["price"]["amount"], 49.0)
        self.assertEqual(item["price"]["currency"], "EUR")
        # Summary carries sizes so the listing page can build its size filter.
        self.assertEqual(item["sizes"], ["S", "M", "L", "XL"])

    def test_unfiltered_listing_omits_where_clause(self):
        response, fake_cluster = self._get()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(fake_cluster.calls)
        self.assertFalse(any("WHERE" in statement for statement in fake_cluster.calls))
        self.assertEqual(response.json()["total"], 42)

    def test_department_filter_reflects_filtered_total(self):
        response, fake_cluster = self._get({"department": "Men"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 7)
        self.assertTrue(
            any("p.category.department = $department" in s for s in fake_cluster.calls)
        )

    def test_type_filter_quotes_reserved_path_segment(self):
        response, fake_cluster = self._get({"type": "Tops"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(any("p.category.`type` = $type" in s for s in fake_cluster.calls))

    def test_subtype_and_color_filters_are_applied(self):
        response, fake_cluster = self._get({"subtype": "Shirts", "color": "navy"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(any("p.category.subtype = $subtype" in s for s in fake_cluster.calls))
        self.assertTrue(any("p.color = $color" in s for s in fake_cluster.calls))

    def test_size_filter_uses_array_predicate(self):
        response, fake_cluster = self._get({"size": "XL"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            any("ANY s IN p.sizes SATISFIES s = $size END" in s for s in fake_cluster.calls)
        )

    def test_price_filters_target_nested_amount(self):
        response, fake_cluster = self._get({"minPrice": 20, "maxPrice": 80})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(any("p.price.amount >= $minPrice" in s for s in fake_cluster.calls))
        self.assertTrue(any("p.price.amount <= $maxPrice" in s for s in fake_cluster.calls))

    def test_unsupported_filters_are_ignored_not_applied(self):
        # `material`, `tag` and `inStock` were removed: no UI reaches them, and
        # `inStock=false` could never match the seed data. Unknown query params
        # must not leak into the WHERE clause.
        response, fake_cluster = self._get(
            {"material": "100% cotton", "tag": "casual", "inStock": "true"}
        )

        self.assertEqual(response.status_code, 200)
        for fragment in ("p.material", "p.tags", "p.stock"):
            with self.subTest(fragment=fragment):
                self.assertFalse(any(fragment in s for s in fake_cluster.calls))

    def test_invalid_department_returns_422(self):
        response, _ = self._get({"department": "invalid-department"})

        self.assertEqual(response.status_code, 422)

    def test_invalid_type_returns_422(self):
        response, _ = self._get({"type": "invalid-type"})

        self.assertEqual(response.status_code, 422)

    def test_price_asc_sort_orders_by_nested_amount(self):
        response, fake_cluster = self._get({"sortBy": "price_asc"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            any("ORDER BY p.price.amount ASC" in s for s in fake_cluster.calls)
        )

    def test_default_sort_is_name_ascending(self):
        response, fake_cluster = self._get()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(any("ORDER BY p.`name` ASC" in s for s in fake_cluster.calls))

    def test_sorts_append_sku_tiebreaker_for_stable_pagination(self):
        response, fake_cluster = self._get({"sortBy": "price_desc"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            any("ORDER BY p.price.amount DESC, p.sku ASC" in s for s in fake_cluster.calls)
        )

    def test_newest_sort_is_no_longer_accepted(self):
        # The documents carry no timestamp, so "newest" was removed with the schema change.
        response, _ = self._get({"sortBy": "newest"})

        self.assertEqual(response.status_code, 422)

    def test_invalid_sort_by_returns_422(self):
        response, _ = self._get({"sortBy": "invalid"})

        self.assertEqual(response.status_code, 422)

    def test_pagination_parameters_are_echoed(self):
        response, _ = self._get({"page": 3, "pageSize": 5})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["page"], 3)
        self.assertEqual(body["pageSize"], 5)

    # ------------------------------------------------------------------
    # Facets endpoint
    # ------------------------------------------------------------------

    def test_facets_aggregate_over_the_whole_collection(self):
        # Facets must not be inferred from one capped page of products, so the
        # endpoint aggregates instead of paginating.
        fake_cluster, patchers = self._build_client()
        with patchers[0], patchers[1]:
            from main import app

            with TestClient(app) as client:
                response = client.get("/api/products/facets")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["minPrice"], 15.0)
        self.assertEqual(body["maxPrice"], 99.0)
        # Values arrive unordered from ARRAY_AGG and are sorted for the client.
        self.assertEqual(body["types"], ["Bottoms", "Tops"])
        self.assertEqual(body["subtypes"], ["Chinos", "Shirts"])
        self.assertEqual(body["colors"], ["black", "navy"])
        self.assertTrue(any("ARRAY_DISTINCT" in s for s in fake_cluster.calls))
        self.assertFalse(any("LIMIT" in s for s in fake_cluster.calls))

    def test_facets_scope_to_department(self):
        fake_cluster, patchers = self._build_client()
        with patchers[0], patchers[1]:
            from main import app

            with TestClient(app) as client:
                response = client.get("/api/products/facets", params={"department": "Women"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            any("p.category.department = $department" in s for s in fake_cluster.calls)
        )

    def test_facets_route_is_not_shadowed_by_the_sku_route(self):
        # /facets is registered before /{sku}; a regression would resolve it as a
        # product lookup and 404.
        _, patchers = self._build_client()
        with patchers[0], patchers[1]:
            from main import app

            with TestClient(app) as client:
                self.assertEqual(client.get("/api/products/facets").status_code, 200)

    def test_facets_tolerate_an_empty_collection(self):
        _, patchers = self._build_client()
        with patchers[0], patchers[1]:
            from main import app

            with patch.object(_FakeCluster, "query", return_value=_FakeQueryResult([{}])):
                with TestClient(app) as client:
                    response = client.get("/api/products/facets")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["types"], [])
        self.assertEqual(body["sizes"], [])
        self.assertEqual(body["minPrice"], 0)
        self.assertEqual(body["maxPrice"], 0)

    # ------------------------------------------------------------------
    # Detail endpoint
    # ------------------------------------------------------------------

    def test_get_product_by_sku_returns_full_detail(self):
        fake_cluster, patchers = self._build_client()
        with patchers[0], patchers[1]:
            from main import app

            with TestClient(app) as client:
                response = client.get("/api/products/SHIRT-STR-NVY-001")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["sku"], "SHIRT-STR-NVY-001")
        self.assertEqual(body["material"], "100% cotton")
        self.assertEqual(body["sizes"], ["S", "M", "L", "XL"])
        self.assertEqual(body["stock"], 40)
        self.assertIn("striped", body["tags"])
        self.assertIn("description", body)

    def test_get_product_by_unknown_sku_returns_404(self):
        fake_cluster, patchers = self._build_client()
        with patchers[0], patchers[1]:
            from main import app

            with TestClient(app) as client:
                response = client.get("/api/products/DOES-NOT-EXIST")

        self.assertEqual(response.status_code, 404)

    def test_get_product_reports_503_on_a_kv_timeout_instead_of_crashing(self):
        # A CouchbaseException other than "not found" (e.g. a KV timeout) must
        # not escape uncaught and crash the ASGI app with a raw 500.
        fake_cluster, patchers = self._build_client()
        captured = io.StringIO()

        with patchers[0], patchers[1]:
            from main import app

            with patch.object(
                _FakeCollection,
                "get",
                side_effect=CouchbaseException(message="Operation failed"),
            ):
                with redirect_stdout(captured):
                    with TestClient(app, raise_server_exceptions=False) as client:
                        response = client.get("/api/products/SHIRT-STR-NVY-001")

        self.assertEqual(response.status_code, 503)
        self.assertIn("SHIRT-STR-NVY-001", response.json()["detail"])
        self.assertIn("[products] ERROR", captured.getvalue())

    # ------------------------------------------------------------------
    # Search endpoint
    # ------------------------------------------------------------------

    def test_search_returns_paginated_response(self):
        response, fake_scope = self._search_get("/api/products/search", {"q": "chinos"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("total", body)
        self.assertIn("page", body)
        self.assertIn("pageSize", body)
        self.assertIn("items", body)
        self.assertEqual(body["total"], 1)
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["items"][0]["name"], "Black Flat-Front Chinos")
        self.assertEqual(body["items"][0]["sku"], "TROUSER-CHN-BLK-001")

    def test_search_uses_scope_relative_index_name(self):
        _, fake_scope = self._search_get("/api/products/search", {"q": "chinos"})

        self.assertEqual(fake_scope.last_index_name, "products_search")

    def test_search_with_stemmed_term_returns_results(self):
        # "flat-front" is tokenised by the FTS analyzer; the fake always returns the
        # test hit, confirming the endpoint delegates to the Search service.
        response, _ = self._search_get("/api/products/search", {"q": "front"})

        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(response.json()["items"]), 0)

    def test_search_without_department_sends_a_plain_disjunction(self):
        _, fake_scope = self._search_get("/api/products/search", {"q": "chinos"})

        self.assertIsInstance(fake_scope.last_query, DisjunctionQuery)

    def test_search_scopes_results_to_the_selected_department(self):
        # The department tab stays visible during a search, so the query has to be
        # narrowed to it rather than returning mixed-department hits.
        response, fake_scope = self._search_get(
            "/api/products/search", {"q": "chinos", "department": "Men"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(fake_scope.last_query, ConjunctionQuery)
        encoded = fake_scope.last_query.encodable
        self.assertIn(
            {"field": "category.department", "term": "Men"},
            encoded["conjuncts"],
        )

    def test_search_with_invalid_department_returns_422(self):
        response, _ = self._search_get(
            "/api/products/search", {"q": "chinos", "department": "Kids"}
        )

        self.assertEqual(response.status_code, 422)

    def test_search_with_empty_query_returns_422(self):
        response, _ = self._search_get("/api/products/search", {"q": "   "})

        self.assertEqual(response.status_code, 422)

    def test_search_tolerates_hits_whose_documents_are_missing(self):
        # A stale FTS index can return an id that no longer exists in KV. The
        # endpoint drops that hit instead of failing the whole request.
        patchers, _ = self._build_search_client()
        with patchers[0], patchers[1]:
            from main import app

            with TestClient(app) as client:
                app.state.couchbase_collection.docs.clear()
                response = client.get("/api/products/search", params={"q": "chinos"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"], [])

    # ------------------------------------------------------------------
    # Vector search endpoint
    # ------------------------------------------------------------------

    def test_vector_search_returns_scored_paginated_response(self):
        response, _, _ = self._vector_get({"q": "something floral for summer"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["page"], 1)
        item = body["items"][0]
        self.assertEqual(item["sku"], "SHIRT-STR-NVY-001")
        self.assertEqual(item["distance"], 0.25)
        # L2_SQUARED over unit-normalized vectors: score is 1 - distance / 2.
        self.assertAlmostEqual(item["score"], 0.875)

    def test_vector_search_route_is_not_shadowed_by_the_sku_route(self):
        # /vector-search is registered before /{sku}; a regression would resolve
        # it as a product lookup and 404.
        response, _, _ = self._vector_get({"q": "floral"})

        self.assertEqual(response.status_code, 200)

    def test_vector_search_embeds_the_natural_language_query(self):
        # The embedding is produced by the Capella-hosted model, not by Couchbase.
        _, _, embed = self._vector_get({"q": "  a warm winter coat  "})

        embed.assert_called_once_with("  a warm winter coat  ")

    def test_vector_search_passes_the_embedding_as_a_query_parameter(self):
        _, fake_cluster, _ = self._vector_get({"q": "floral"})

        named = [
            options["named_parameters"]
            for options in fake_cluster.options
            if options is not None and "named_parameters" in options
        ]
        self.assertTrue(named)
        self.assertEqual(named[0]["queryVector"], _QUERY_VECTOR)

    def test_vector_search_orders_by_approximate_distance_over_the_vector_index(self):
        _, fake_cluster, _ = self._vector_get({"q": "floral"})

        statement = next(s for s in fake_cluster.calls if "APPROX_VECTOR_DISTANCE" in s)
        self.assertIn("p.descriptive_vectors", statement)
        self.assertIn("USE INDEX (`composite_descriptive_vectors` USING GSI)", statement)
        # The ordering term must be the function call itself for the vector index
        # scan to be pushed down; the `distance` alias would not qualify.
        self.assertIn("ORDER BY APPROX_VECTOR_DISTANCE(", statement)
        self.assertIn("LIMIT $topK", statement)

    def test_vector_search_prints_the_sql_statement_to_the_terminal(self):
        # The whole point of this print is that it is visible without relying
        # on logging handlers being configured.
        captured = io.StringIO()
        with redirect_stdout(captured):
            self._vector_get({"q": "floral"})

        output = captured.getvalue()
        self.assertIn("[vector-search] SQL++:", output)
        self.assertIn("APPROX_VECTOR_DISTANCE(p.descriptive_vectors", output)
        # The embedding itself is summarised, not dumped float-by-float.
        self.assertIn("<3-dim vector>", output)
        self.assertNotIn(str(_QUERY_VECTOR), output)

    def test_vector_search_prints_the_retry_statement_without_the_hint(self):
        fake_cluster, patchers = self._build_vector_client()

        def query(statement, options=None):
            if "USE INDEX" in statement:
                raise CouchbaseException(message="no index available")
            return _FakeQueryResult([dict(_VECTOR_ROW)])

        captured = io.StringIO()
        with patchers[0], patchers[1], patchers[2]:
            from main import app

            with patch.object(_FakeCluster, "query", side_effect=query):
                with redirect_stdout(captured):
                    with TestClient(app) as client:
                        client.get("/api/products/vector-search", params={"q": "floral"})

        output = captured.getvalue()
        self.assertIn("retrying without the hint", output)
        self.assertIn("Retrying vector search query without the index hint:", output)

    def test_vector_search_uses_the_configured_metric(self):
        os.environ["COUCHBASE_VECTOR_METRIC"] = "COSINE"
        try:
            response, fake_cluster, _ = self._vector_get({"q": "floral"})
        finally:
            os.environ["COUCHBASE_VECTOR_METRIC"] = "L2_SQUARED"

        statement = next(s for s in fake_cluster.calls if "APPROX_VECTOR_DISTANCE" in s)
        self.assertIn('"COSINE"', statement)
        # COSINE distance inverts exactly: score is 1 - distance.
        self.assertAlmostEqual(response.json()["items"][0]["score"], 0.75)

    def test_vector_search_plain_l2_over_normalized_vectors_squares_the_distance(self):
        # L2 (not squared) needs distance**2 in the same "2 - 2cos" identity that
        # L2_SQUARED uses directly.
        os.environ["COUCHBASE_VECTOR_METRIC"] = "L2"
        try:
            response, _, _ = self._vector_get({"q": "floral"})
        finally:
            os.environ["COUCHBASE_VECTOR_METRIC"] = "L2_SQUARED"

        # distance=0.25: score = 1 - 0.25**2 / 2 = 0.96875, rounded to 4 places.
        self.assertAlmostEqual(response.json()["items"][0]["score"], 0.9688, places=4)

    def test_vector_search_score_is_clamped_for_a_large_distance(self):
        # A distance beyond what the "2 - 2cos" identity can produce for unit
        # vectors (e.g. a stale/non-normalized embedding) must not yield a
        # score outside the documented [0, 1] range.
        fake_cluster, patchers = self._build_vector_client()
        with patchers[0], patchers[1], patchers[2]:
            from main import app

            with patch.object(
                _FakeCluster,
                "query",
                return_value=_FakeQueryResult([{**_SUMMARY_ROW, "distance": 9.0}]),
            ):
                with TestClient(app) as client:
                    response = client.get("/api/products/vector-search", params={"q": "floral"})

        self.assertEqual(response.json()["items"][0]["score"], 0.0)

    def test_vector_search_rejects_an_unsupported_metric(self):
        os.environ["COUCHBASE_VECTOR_METRIC"] = "MANHATTAN"
        try:
            response, _, _ = self._vector_get({"q": "floral"})
        finally:
            os.environ["COUCHBASE_VECTOR_METRIC"] = "L2_SQUARED"

        self.assertEqual(response.status_code, 500)

    def test_vector_search_applies_the_sidebar_filters_as_predicates(self):
        # The composite vector index exists so a nearest-neighbour scan can be
        # narrowed; the filters must reach the WHERE clause, not be dropped.
        _, fake_cluster, _ = self._vector_get(
            {"q": "floral", "department": "Men", "color": "navy", "maxPrice": 80}
        )

        statement = next(s for s in fake_cluster.calls if "APPROX_VECTOR_DISTANCE" in s)
        self.assertIn("p.category.department = $department", statement)
        self.assertIn("p.color = $color", statement)
        self.assertIn("p.price.amount <= $maxPrice", statement)

    def test_vector_search_without_filters_omits_the_where_clause(self):
        _, fake_cluster, _ = self._vector_get({"q": "floral"})

        statement = next(s for s in fake_cluster.calls if "APPROX_VECTOR_DISTANCE" in s)
        self.assertNotIn("WHERE", statement)

    def test_vector_search_with_empty_query_returns_422(self):
        response, _, _ = self._vector_get({"q": "   "})

        self.assertEqual(response.status_code, 422)

    def test_vector_search_with_missing_query_returns_422(self):
        response, _, _ = self._vector_get()

        self.assertEqual(response.status_code, 422)

    def test_vector_search_with_invalid_department_returns_422(self):
        response, _, _ = self._vector_get({"q": "floral", "department": "Kids"})

        self.assertEqual(response.status_code, 422)

    def test_vector_search_retries_without_the_index_hint(self):
        # A forced index that cannot serve the statement fails outright; the
        # planner gets a second chance rather than the request failing.
        fake_cluster, patchers = self._build_vector_client()
        statements: list[str] = []

        def query(statement, options=None):
            statements.append(statement)
            if "USE INDEX" in statement:
                raise CouchbaseException(message="no index available")
            return _FakeQueryResult([dict(_VECTOR_ROW)])

        with patchers[0], patchers[1], patchers[2]:
            from main import app

            with patch.object(_FakeCluster, "query", side_effect=query):
                with TestClient(app) as client:
                    response = client.get("/api/products/vector-search", params={"q": "floral"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["items"]), 1)
        self.assertEqual(len(statements), 2)
        self.assertNotIn("USE INDEX", statements[1])

    def test_vector_search_reports_502_when_the_query_cannot_run(self):
        fake_cluster, patchers = self._build_vector_client()

        with patchers[0], patchers[1], patchers[2]:
            from main import app

            with patch.object(
                _FakeCluster, "query", side_effect=CouchbaseException(message="boom")
            ):
                with TestClient(app, raise_server_exceptions=False) as client:
                    response = client.get("/api/products/vector-search", params={"q": "floral"})

        self.assertEqual(response.status_code, 502)

    def test_vector_search_drops_hits_without_a_distance(self):
        # A document with no embedding cannot be ranked against the query.
        fake_cluster, patchers = self._build_vector_client()

        with patchers[0], patchers[1], patchers[2]:
            from main import app

            with patch.object(
                _FakeCluster, "query", return_value=_FakeQueryResult([dict(_SUMMARY_ROW)])
            ):
                with TestClient(app) as client:
                    response = client.get("/api/products/vector-search", params={"q": "floral"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"], [])
        self.assertEqual(response.json()["total"], 0)

    # ------------------------------------------------------------------
    # Degraded mode
    # ------------------------------------------------------------------

    def test_product_endpoints_return_503_when_couchbase_is_unavailable(self):
        # Startup keeps the API up when Couchbase cannot be reached, so the
        # product endpoints must report 503 rather than blowing up with a 500.
        patchers = (
            patch("main.initialize_couchbase", side_effect=RuntimeError("no cluster")),
            patch("main.shutdown_couchbase", return_value=None),
        )
        with patchers[0], patchers[1]:
            from main import app

            with TestClient(app, raise_server_exceptions=False) as client:
                for path in (
                    "/api/products",
                    "/api/products/ABC",
                    "/api/products/search?q=x",
                    "/api/products/vector-search?q=x",
                ):
                    with self.subTest(path=path):
                        self.assertEqual(client.get(path).status_code, 503)

    def test_degraded_mode_recovers_once_couchbase_comes_back(self):
        # Degraded mode must heal on its own: a request made after Couchbase
        # recovers reconnects instead of returning 503 until the next restart.
        fake_cluster = _FakeCluster()
        handles = (fake_cluster, SimpleNamespace(), SimpleNamespace(), _FakeCollection())
        patchers = (
            patch("main.initialize_couchbase", side_effect=RuntimeError("no cluster")),
            patch("main.shutdown_couchbase", return_value=None),
            patch("main.RECONNECT_COOLDOWN_SECONDS", 0),
        )
        with patchers[0] as init, patchers[1], patchers[2]:
            from main import app

            with TestClient(app, raise_server_exceptions=False) as client:
                self.assertEqual(client.get("/api/products").status_code, 503)

                # Couchbase comes back; the next request should reconnect.
                init.side_effect = None
                init.return_value = handles
                self.assertEqual(client.get("/api/products").status_code, 200)

    def test_reconnect_attempts_are_rate_limited_while_degraded(self):
        # A sustained outage must not turn every request into its own bootstrap.
        patchers = (
            patch("main.initialize_couchbase", side_effect=RuntimeError("no cluster")),
            patch("main.shutdown_couchbase", return_value=None),
            patch("main.RECONNECT_COOLDOWN_SECONDS", 300),
        )
        with patchers[0] as init, patchers[1], patchers[2]:
            from main import app

            with TestClient(app, raise_server_exceptions=False) as client:
                for _ in range(3):
                    self.assertEqual(client.get("/api/products").status_code, 503)

        # Only the startup attempt runs; the cooldown suppresses the rest.
        self.assertEqual(init.call_count, 1)

    def test_health_stays_available_when_couchbase_is_unavailable(self):
        patchers = (
            patch("main.initialize_couchbase", side_effect=RuntimeError("no cluster")),
            patch("main.shutdown_couchbase", return_value=None),
        )
        with patchers[0], patchers[1]:
            from main import app

            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


if __name__ == "__main__":
    unittest.main()
