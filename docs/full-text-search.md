# Search service (FTS)

Keyword search from the navigation bar, backed by a scope-level Search index.

## What is implemented

- `GET /api/products/search?q=...&department=...` — paginated keyword search
  returning each hit's relevance score.
- An **ℹ️ info button** by the results heading showing the exact Search request
  body Couchbase ran, rendered from the object handed to `scope.search()`.
- The selected department tab stays in force during a search.

## The index

Created by `backend/scripts/create_indexes.py` as a **scope-level** index 
(`products_search`). The name must be scope-relative — `scope.search()` resolves it 
inside `COUCHBASE_SCOPE`, so a `bucket.scope.index` value is rejected up front.

The mapping is **explicit, not dynamic** (`default_mapping` disabled):

| Path | Analyzer | In `_all` |
|---|---|---|
| `name`, `description`, `tags`, `color`, `material`, `category.type`, `category.subtype` | `en` | yes |
| `category.department` | `keyword` | **no** |

`category` is an object, so its leaves are mapped individually —
`_build_fts_properties()` turns dotted paths into the nested mapping FTS expects.
`department` uses the `keyword` analyzer so the value stays one token and
matches exactly, and stays out of `_all` so a free-text query for "men" does not
match on it; it is queried with a `TermQuery`.

Existing indexes are left alone — to pick up a mapping change, drop the index in
the Capella UI and re-run.

## The Search Query

Every indexed field feeds the composite `_all` field, so the query matches
`_all` once instead of one `MatchQuery` per field:

```
Disjunction(
  Match(q, field="_all", analyzer="en"),                  # the whole phrase
  Conjunction(Match(word, field="_all", analyzer="en")     # every word, separately
              for word in q.split())
)
```

A document matching every individual word is a stronger signal than a partial
phrase match, so the per-word conjunction competes alongside the phrase match.
A selected department wraps the whole thing in a conjunction with the `TermQuery`.

Scores are the Search service's own (TF-IDF/BM25) and are **not** normalised —
unlike vector search's 0–1 `score`, so the two are not comparable and the UI
labels them differently.

Search returns ids and scores only; hits are resolved through the Data service
in one batched `get_multi()`. An unresolvable hit means the index lags the
collection, logged as a warning noting that `total` overstates the retrievable
results.

## Agents use: `SEARCH()` in SQL++ query

Both agents are instructed to use FTS from inside SQL++ when a question
describes a product rather than filtering on a field — the Query service pushing
a predicate into the same Search index (see [MCP](mcp.md)):

```sql
SELECT p.meta().id, p.description
FROM `webshop`.`webshop-scope`.`products` AS p
WHERE SEARCH(p.description, "floral print")
ORDER BY SEARCH_SCORE() DESC LIMIT 5;
```

## Out of scope

Facets from FTS for the listing page filter options (a SQL++ aggregation covers the whole collection instead) · highlighting / snippets · fuzzy matching, synonyms, custom analyzers · geo and date range queries · sorting by a field.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Nothing found right after seeding | FTS indexing is asynchronous; it lags by a few seconds |
| `Couchbase FTS index is not configured` (500) | `COUCHBASE_FTS_INDEX` is unset in backend/.env |
| Index name rejected on creation | the value contains a `.`; use the scope-relative name |
| A mapping change did not take effect | existing indexes are left untouched — drop it first |
| Warning about unresolved hits | the index is stale relative to KV, or documents were deleted |