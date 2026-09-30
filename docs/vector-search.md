# Vector search (text embeddings)

Natural-language product search — *"a light linen shirt for a summer wedding"* —
from the sidebar's **"Describe what you are looking for"** box, calling
`GET /api/products/vector-search`.

> **Not the Search service.** Ranking runs inside SQL++ against a **vector GSI
> index**, served by **Index + Query**. 

## What is implemented

- Nearest-neighbour search over the products collection, ranked in Couchbase.
- **The sidebar filters apply**, as ordinary `WHERE` predicates — after the
  scan, not pushed into the index ([why](#why-one-vector-only-index)).
- A similarity score on every tile, normalised to 0–1.
- An **ℹ️ info button** showing the exact SQL++ that produced the ranking,
  including which attempt (hinted or un-hinted) ran. Both are also printed to
  the backend terminal, with the embedding shown as `<N-dim vector>`.
- *"Clear all"* drops the query and scores, returning the plain listing.

## Vector Search Query

1. **Embed the user query** — `services/embeddings.py` calls the Capella-hosted
   embedding model's `/v1/embeddings` API ([Model service](model-service.md)).
2. **Rank in Couchbase** — the vector is the `$queryVector` *named parameter*:

   ```sql
   SELECT p.sku, p.`name`, p.image, p.color, p.category, p.price, p.sizes,
          APPROX_VECTOR_DISTANCE(p.descriptive_vectors, $queryVector, "L2_SQUARED") AS distance
   FROM `webshop`.`webshop-scope`.`products` AS p USE INDEX (`composite_descriptive_vectors` USING GSI)
   WHERE p.category.department = $department AND p.price.amount <= $maxPrice
   ORDER BY APPROX_VECTOR_DISTANCE(p.descriptive_vectors, $queryVector, "L2_SQUARED")
   LIMIT $topK
   ```

3. **Score and paginate** — `top_k` bounds the whole result set, so pagination
   slices one scan and `total` stays stable across page turns.

Three details that are easy to get wrong:

- **`ORDER BY` repeats the whole expression** instead of using the `distance`
  alias; pushing the scan into the vector index requires the ordering term to be
  the `APPROX_VECTOR_DISTANCE` call itself.
- **The metric is interpolated, not parameterised** — the planner must see a
  literal to match the index. It is validated against a fixed allow-list (`L2`,
  `L2_SQUARED`, `EUCLIDEAN`, `EUCLIDEAN_SQUARED`, `COSINE`, `DOT`) first, so it
  is not an injection point.
- **The index hint is attempted, then dropped.** A forced index fails outright
  when it cannot serve the statement (still building, leading key not filtered),
  so the query is retried without `USE INDEX` on a `CouchbaseException`. Only if
  both fail is it a `502`, naming the index, field and metric to check.

## Distance to score

`_similarity_score()` maps distance onto a 0–1 similarity (higher = closer), so
tiles show one comparable number whatever the index was built with. Because
`descriptive_vectors` are unit-normalized, the L2 family is *exact* rather than
merely monotonic:

| Metric | Conversion |
|---|---|
| `L2_SQUARED`, `EUCLIDEAN_SQUARED` | `1 - distance / 2` |

All clamped to `[0, 1]`, so a negative cosine reads as "unrelated". A document
with no embedding returns a null distance and is dropped.

## Why one vector-only index

The index carries **one key: the vector field**. A GSI index is only eligible
when the query filters on its **leading key**, and every sidebar filter here is
optional — an index led by `color` is unusable the moment that filter is blank,
and covering every combination means one index each.

**The trade-off is post-filtering.** `LIMIT $topK` picks the nearest matches
across the *whole* collection and the `WHERE` clause then discards non-matches,
so a narrow filter can return fewer rows than `topK`, occasionally none, even
when matching products exist. With `topK` capped at 20 that is reachable in a
demo — widen the filters or raise `topK`. At 150 documents the scan is instant
either way, so this is about behaviour at scale, not demo latency.

## How `descriptive_vectors` got there

Via the **AI Data Plane Data Processing + Vectorization service**, driven from
the **Capella UI** — a managed workflow, with no code in this repo by design.

The app only ever *reads* `descriptive_vectors`, so re-running the workflow
after a catalogue change needs no code change — but if the model changes,
`CAPELLA_EMBEDDING_MODEL` used in this app must change with it.
`CAPELLA_EMBEDDING_MODEL` must be the model that produced `descriptive_vectors`,
or the query vector has the wrong dimensionality.

## Out of scope

Image embeddings · creating the embeddings or the vector index from code (the UI
workflow is the feature) · hybrid search (keyword and vector stay two separately
explainable paths) · re-ranking · vector search through the Search service.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `502` naming the index and metric | the index is missing, not over `descriptive_vectors`, or the metric mismatches |
| The hint is dropped every time | the index is not `online` (deferred build never run), or cannot serve that statement |
| Scores near-identical or nonsensical | `CAPELLA_EMBEDDING_MODEL` is not the model that produced the vectors |
| Results unranked / empty | documents have no `descriptive_vectors`; run the vectorization workflow |
| `COUCHBASE_VECTOR_METRIC=... is not a supported metric` (500) | typo; use one of the six allow-listed values |