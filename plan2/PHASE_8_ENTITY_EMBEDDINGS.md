# Phase 8: Entity-Level Embeddings (Optional)

Objective:

- embed promoted concepts themselves so users can semantically search the concept layer and the viz can name sparse clusters more meaningfully

## Workstream

Primary workstream:

- a new `entity_embeddings` table computed on concept refresh, with a lightweight `/api/concepts/search` endpoint and a viz cluster-naming fallback

## Current Limitation

`entities.canonical_name` is only reachable through exact normalized-key match (`find_concepts_for_terms`) or SQL `LIKE` in `list_concepts`. A query for "fate" will not surface `Destiny`, `Fortune`, or `Suerte` even though they are semantically the same bucket. The viz also has no way to name a cluster whose chunks have few or no concept mentions.

## Product Shape

- every `entities` row of `entity_type = 'concept'` with `mention_count >= 2` has a cached embedding derived from `canonical_name + " — " + top mention snippet`
- a new `/api/concepts/search?q=...&top_k=...` endpoint returns semantically similar concepts
- the viz uses entity embeddings only when the raw concept-mention set for a cluster is too sparse to name it well

## Tasks

- schema addition:
  ```
  CREATE TABLE IF NOT EXISTS entity_embeddings (
      entity_id INTEGER PRIMARY KEY,
      model_name TEXT NOT NULL,
      vector_json TEXT NOT NULL,
      created_at TEXT NOT NULL,
      FOREIGN KEY(entity_id) REFERENCES entities(id) ON DELETE CASCADE
  );
  ```
- compute path in `refresh_concepts` / `_refresh_entity_mention_counts`:
  - pick top N mentions per entity (prefer `wikilink` → `definition` → `emphasis` → longest snippet)
  - embed `canonical_name + " — " + joined mention snippets (truncated ~500 chars)`
  - write into `entity_embeddings`, replacing stale vectors when `canonical_name` or mention set changes
- new endpoint `GET /api/concepts/search?q=...&top_k=20`:
  - embed the query once, cosine against `entity_embeddings`, return `entities` rows sorted by score
  - when [Phase 7](./PHASE_7_VECTOR_INDEX.md) is live, route through a second `entity_vectors` vec0 table with the same dual-write pattern
- viz integration in `app/web.py::_compute_viz_data`:
  - if a cluster has no concept mentions AND at least N chunks, take the top embedded entities closest to the cluster centroid as a naming fallback
- CLI: `personal-memory concepts search --query "..."` mirroring the endpoint
- web UI: optional concept search surface (out of scope if keeping this phase minimal)

## Primary Files

- `app/schema.sql`
- `app/db.py`
- `app/ingest/register.py`
- `app/retrieval/concept_search.py`
- `app/web.py`
- `app/cli.py`
- `tests/test_concept_search.py` (new or extended)

## Dependencies

- Requires [Phase 3](./PHASE_3_CONCEPT_NORMALIZATION.md) so entity-level embeddings aren't fragmented across trivial variants.
- Benefits from [Phase 7](./PHASE_7_VECTOR_INDEX.md) for the `entity_vectors` ANN index; without it, entity search falls back to a Python cosine scan that is cheap because there are usually far fewer entities than chunks.
- Optional — the whole phase can be skipped without breaking earlier phases.

## Tests

- entity refresh re-embeds only when `canonical_name` or mention set changed
- concept search returns expected neighbors on a small fixture (e.g. `"destiny"` retrieves `Fortune`, `Fate`)
- empty-cluster naming fallback activates only when the concept-mention path yields nothing
- removing an entity also removes its embedding row

## Exit Criteria

- `/api/concepts/search` answers in <200 ms for vaults with up to a few thousand concepts
- viz names every cluster sensibly, even for sparse concept coverage
- concept refresh remains idempotent

## Milestone Focus

Milestone:

- Semantic Concept Layer
