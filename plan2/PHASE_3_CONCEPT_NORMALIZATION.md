# Phase 3: Concept Normalization

Objective:

- collapse trivial surface variants (diacritics, plurals) into the same canonical entity so concept lists, counts, and boosts are stable

## Workstream

Primary workstream:

- normalization in `app/processing/concepts.py::normalize_key` and merge logic in `app/ingest/register.py::_upsert_entity`

## Current Limitation

`normalize_key` today is only case-folding plus `_`/`-` collapsing:

```
# app/processing/concepts.py
def normalize_key(value: str) -> str:
    cleaned = value.replace("_", " ").replace("-", " ")
    cleaned = _WHITESPACE.sub(" ", cleaned).strip().lower()
    return cleaned
```

Consequences:

- `México` and `Mexico` become distinct entities
- `Quijote` and `quijotes` fragment concept counts
- `find_concepts_for_terms` happily matches stopword keys if a user's rewritten query contains them

## Tasks

- diacritic fold in `normalize_key`:
  - `unicodedata.normalize("NFKD", cleaned)` then strip combining marks
  - also collapse the curly apostrophes `’` and `‘` to `'` before normalization (they already appear in the regexes)
- conservative plural collapse:
  - strip a trailing `s` or `es` only when the resulting base has ≥4 characters AND another entity already exists with the base key (or will be created in the same run)
  - never touch stopwords, acronyms (uppercase-only source), or single-word keys shorter than 4 chars
- normalized-key stoplist (piggyback off `_BODY_STOPWORDS`) so `find_concepts_for_terms` never returns a match for a key that is entirely stopwords
- merge support in `_upsert_entity`:
  - when the normalized key resolves to an existing entity with a different canonical_name, keep the richer canonical name (longer, more capitalization) and increment `mention_count`
  - when a [Phase 1](./PHASE_1_STRUCTURE_FILTER_HARDENING.md) reclassification or this normalization change causes two rows to collapse, reassign `entity_mentions.entity_id` from the loser to the survivor and `DELETE` the loser (inside a transaction)

## Primary Files

- `app/processing/concepts.py`
- `app/ingest/register.py`
- `tests/test_normalization.py` (new)
- `tests/test_concepts.py`

## Dependencies

- Independent of other phases, but pairs well with the `concepts reclassify` CLI from [Phase 1](./PHASE_1_STRUCTURE_FILTER_HARDENING.md) — a single reclassify pass can both restructure and re-normalize.

## Tests

- `normalize_key("México") == normalize_key("Mexico")`
- `normalize_key("Don Quijote’s") == normalize_key("Don Quijote")` (punctuation + plural)
- plural collapse is skipped when the base does not already exist (`"class"` stays `"class"` on first encounter)
- merge path: ingesting the same concept under two normalizable variants results in one entity with combined mentions
- `find_concepts_for_terms` returns empty for queries consisting only of stopwords

## Exit Criteria

- concept lists on a multilingual vault no longer double-count diacritic variants
- `personal-memory concepts list` mention counts are stable across runs when source text adds/removes accent marks
- refresh is still idempotent
- no entity rows are lost without their mentions being reattached

## Milestone Focus

Milestone:

- Stable Canonical Concepts
