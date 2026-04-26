# Phase 6: Weighted FTS and Exact-Concept Boost

Objective:

- make heading, title, and concept-exact matches outrank incidental body matches in keyword search and in the hybrid fusion

## Workstream

Primary workstream:

- BM25 weighting in `app/retrieval/keyword_search.py` and a complementary exact-key concept boost in `app/retrieval/hybrid_search.py`

## Current Limitation

Keyword search uses `bm25(chunks_fts)` with default weights, so `document_title`, `section_title`, and `text` all contribute equally:

```
# app/retrieval/keyword_search.py
SELECT ..., bm25(chunks_fts) AS score FROM chunks_fts ... ORDER BY score
```

And `_build_fts_query` always OR-joins bare terms:

```
return " OR ".join(f'"{term}"' for term in terms)
```

So a body mention of `"quijote"` can tie or beat a chunk whose `document_title` is literally `"Don Quijote"`. Concept-aware boost exists (`_apply_concept_boost`) but only fires on entities found via `find_concepts_for_terms`, not on exact normalized-key matches of the user query tokens.

## Tasks

- switch `keyword_search` to weighted BM25: `bm25(chunks_fts, 3.0, 5.0, 1.0)` for `document_title`, `section_title`, `text`
  - note: `chunks_fts.chunk_id` is `UNINDEXED`, so the weight vector aligns to the 3 indexed columns in declaration order — confirm with a test that flips a heading-only match above a body-only match
- prefer `NEAR` / phrase clauses when the user provides ≥2 alphanumeric tokens:
  - build both an `AND`-style phrase clause (`NEAR("a" "b", 5)`) and the existing OR fallback, then `UNION` them so phrase hits rank highest without losing broad recall
  - keep single-token queries on the current OR path
- add an exact-normalized-key concept boost in `hybrid_search`:
  - for each `term` in the query, compute `normalize_key(term)` (and adjacent bi-grams, like `_candidate_keys` does today)
  - if a key matches `entities.normalized_key` exactly AND that entity is mentioned in the candidate chunk, add a capped boost (e.g. `+0.08`, `max 0.15`) on top of the existing `_apply_concept_boost`
  - record the boost in `score_explanation` under a new `exact_concept_boost` key
- add a retrieval debug toggle (`--debug-scores` on `personal-memory search`) that dumps the full explanation per result

## Primary Files

- `app/retrieval/keyword_search.py`
- `app/retrieval/hybrid_search.py`
- `app/cli.py`
- `tests/test_keyword_search.py`
- `tests/test_hybrid_search.py` (new if not present)

## Dependencies

- Benefits from [Phase 1](./PHASE_1_STRUCTURE_FILTER_HARDENING.md) and [Phase 3](./PHASE_3_CONCEPT_NORMALIZATION.md) so the exact-concept boost never fires on structural strings or diacritic-fragmented entities.
- Independent of [Phase 4](./PHASE_4_BREADCRUMB_CHUNKS.md) and [Phase 7](./PHASE_7_VECTOR_INDEX.md).

## Tests

- weighted BM25: a chunk whose only match is in `section_title` outranks a chunk whose only match is in `text`
- phrase preference: `"don quijote"` as a two-token query ranks phrase-matching chunks above chunks that only contain the tokens separately
- exact-concept boost: when the user query normalizes to an entity key, chunks that mention that entity receive the extra boost, capped at the documented maximum
- `score_explanation` in the search API payload exposes both `concept_boost` and `exact_concept_boost`
- small golden-question regression: precision@3 is equal-or-better than baseline on a fixture set of queries

## Exit Criteria

- headings and titles consistently outrank incidental body hits
- retrieval debug output clearly separates `keyword_score`, `semantic_score`, `metadata_score`, `concept_boost`, `exact_concept_boost`, and `final_score`
- no regressions on the golden-question fixture

## Milestone Focus

Milestone:

- Field-Aware Keyword Retrieval
