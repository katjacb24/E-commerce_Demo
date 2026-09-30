# Data service (KV) and Index + Query service (SQL++)

Everything the web shop renders outside of search comes from these two services.

## The data model

One collection: `products`; 150 seeded documents keyed `product::<sku>`.
Document example: 

```json
{
  "sku": "SHIRT-STR-NVY-001",
  "name": "Vertical Stripe Long-Sleeve Shirt",
  "description": "Men's long-sleeve casual shirt in navy, pink and light-blue stripes ...",
  "image": "39773.jpg",
  "category": { "department": "Men", "type": "Tops", "subtype": "Shirts" },
  "color": "navy",
  "material": "100% cotton",
  "sizes": ["S", "M", "L", "XL"],
  "price": { "amount": 49.0, "currency": "EUR" },
  "tags": ["casual", "striped", "long-sleeve"],
  "stock": 40
}
```

`backend/models/product.py` models three tiers: 
- `ProductSummary` (tiles),
- `ProductDetail` (product page), plus 
- scored variants for the search endpoints.

Documents carry **no timestamp**, so there is no "newest" sort — name or price
only, with `sku` as tiebreaker to keep pagination stable.

`descriptive_vectors` is *not* seeded; it is written into the stored documents
afterwards by a Capella UI workflow — see [Vector search](vector-search.md).

## Data service (KV)

Used wherever a document is addressed by ID rather than by predicate:

| Operation | Where |
|---|---|
| `collection.get(product::<sku>)` | `GET /api/products/{sku}` — the page knows the key |
| `collection.get_multi(keys)` | after every FTS search — Search returns ids, tiles need documents |
| `collection.upsert(...)` | `backend/scripts/seed_data.py` |

The search path **projects nothing from the FTS index** and re-reads from KV.
`_document_key()` is idempotent about the `product::` prefix, and hits that miss
are retried unprefixed. A missing document is a `404`; any other
`CouchbaseException` is a `503` saying a retry may succeed.

## Index + Query service (SQL++)

Three endpoints, all via `cluster.query()` with **named parameters** — no string
interpolation of user input.

**`GET /api/products`** — listing. `_build_filters()` turns the sidebar into
`WHERE` predicates: department, type, subtype and color as equality, price as a
range, size as `ANY s IN p.sizes SATISFIES s = $size END`. The same function is
reused by vector search, so the sidebar means the same thing in both modes
(though [applied after the scan](vector-search.md#why-one-vector-only-index)
there). Each request runs the page (`LIMIT`/`OFFSET`) plus a
`SELECT RAW COUNT(1)` over the same predicates.

**`GET /api/products/facets`** — one aggregation over the whole (optionally
department-scoped) collection, so dropdowns never depend on the current page:

```sql
SELECT ARRAY_DISTINCT(ARRAY_AGG(p.category.`type`)) AS types,
       ARRAY_DISTINCT(ARRAY_FLATTEN(ARRAY_AGG(p.sizes), 1)) AS sizes,
       MIN(p.price.amount) AS minPrice, MAX(p.price.amount) AS maxPrice, ...
FROM `bucket`.`scope`.`products` AS p
```

**`GET /api/products/vector-search`** — also SQL++; see [Vector search](vector-search.md).

## The indexes

`backend/scripts/create_indexes.py` creates GSI indexes and is safe to re-run (existing
indexes are left untouched): `idx_products_primary` plus one each on
`category.department`, `category.type`, `category.subtype`, `color`,
`price.amount` and `name`. 
The primary index covers unfiltered listings, the facet aggregates and the
`size` filter. 

Composite **vector** index is created in the Capella UI. 

## Connection handling

`backend/db/connection.py` connects once at startup with raised timeouts (30s
bootstrap, 5s DNS, 30s ready). If Couchbase is unreachable the API still starts in 
**degraded mode**: product endpoints answer `503` and retry on demand, at most once 
every 10 seconds, so a transient outage heals without a restart.

## Out of scope

Writes from the application (the shop is read-only; MCP runs read-only too) ·
transactions · sub-document operations · collection/scope management from code ·
Couchbase Analytics.