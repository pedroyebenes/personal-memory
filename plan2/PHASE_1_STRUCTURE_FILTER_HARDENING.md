# Phase 1: Structure Filter Hardening

Objective:

- prevent structural labels (chapters, front-matter headings, dates) from entering the `concept` entity type, so concept-aware surfaces stay clean

## Workstream

Primary workstream:

- classification-time filtering in `app/processing/concepts.py`, complemented by a one-shot reclassification pass over existing rows

## Current Limitation

`_STRUCTURAL_LABEL_PATTERNS` in `app/processing/concepts.py` only catches bare, fully-matching forms:

```
^(?:cap[ií]tulo|chapter|part|parte|book|libro|section|secci[oó]n)\s+(?:[ivxlcdm]+|\d+|...)$
```

It misses common real-world headings such as:

- `Capítulo IV: Donde se cuenta la estraña aventura...`
- `Chapter 3 — The Road Home`
- `Prólogo`, `Epílogo`, `Introducción`, `Prefacio`, `Dedicatoria`, `Índice`, `Tabla de Contenidos`, `Glosario`, `Apéndice`, `Nota del Autor`
- `Parte Primera`, `Capítulo Segundo`, `Libro Tercero`
- ISO or natural-language dates (`2026-04-20`, `April 20, 2026`)
- Weekday names used as daily-note headings (`Lunes`, `Monday`)

Additionally, `extract_concept_mentions` applies the structural classification only to `title`, `heading`, and `filename`. An `alias` mention that equals a chapter string still becomes a concept.

## Tasks

- extend `_STRUCTURAL_LABEL_PATTERNS` with:
  - subtitled chapter/section: `^(cap[ií]tulo|chapter|part|parte|book|libro|section|secci[oó]n|tomo)\s+\S+(\s*[:—–-]\s+.+)?$`
  - front-matter sections: `^(pr[oó]logo|ep[ií]logo|introducci[oó]n|pref[aá]cio|dedicatoria|[ií]ndice|tabla\s+de\s+contenidos|glosario|ap[eé]ndice|nota\s+del\s+autor|acknowledgments?)\b`
  - ordinal forms: `^(parte|cap[ií]tulo|libro)\s+(primero|segundo|tercero|cuarto|quinto|sexto|s[eé]ptimo|octavo|noveno|d[eé]cimo|und[eé]cimo|duod[eé]cimo)\b`
  - ISO / natural dates: `^\d{4}-\d{2}-\d{2}$`, `^\d{4}/\d{2}/\d{2}$`, month-name + day + optional year
  - weekday names in Spanish and English
- add `"alias"` to `_STRUCTURAL_METHODS` (or a distinct set), so alias mentions that equal a structural string also get `entity_type='structure'`
- update the stop-term constants in `_cluster_name_from_rows` (`app/web.py`) to share the same vocabulary so cluster names never pick up these phrases even before the viz consumes the entity layer
- add a `concepts reclassify` CLI subcommand in `app/cli.py` that re-applies `classify_entity_type` to every row in `entities` without dropping `entity_mentions`:
  - recompute `entity_type` for each entity based on its normalized_key and the set of extraction methods already recorded
  - if two entities now collapse (rare — only when [Phase 3](./PHASE_3_CONCEPT_NORMALIZATION.md) is also live), defer to Phase 3's merge helper

## Primary Files

- `app/processing/concepts.py`
- `app/cli.py`
- `app/web.py` (shared stop-term vocabulary)
- `tests/test_concepts.py`

## Dependencies

- Independent of other phases. Runs before [Phase 2](./PHASE_2_VIZ_CONCEPT_SURFACE.md) so the viz immediately shows cleaner concepts.

## Tests

- classification regression for:
  - `Capítulo IV: Donde se cuenta...` → `structure`
  - `Prólogo` → `structure`
  - `Parte Primera` → `structure`
  - `2026-04-20` → `structure`
  - `Monday` → `structure`
  - `Dulcinea del Toboso` → `concept`
- `alias` mentions that equal a chapter string end up classified as `structure`
- `concepts reclassify` is idempotent: running it twice produces the same rows
- `entity_mentions` rows are preserved across reclassification (provenance-preserving)

## Exit Criteria

- existing `entities` table can be cleaned up on an existing DB with `personal-memory concepts reclassify` — no reindex required
- `personal-memory concepts list --type concept` on a book-heavy vault no longer shows chapter/front-matter labels
- concept-aware retrieval boost no longer fires on date or chapter strings
- tests cover every new structural pattern

## Milestone Focus

Milestone:

- Clean Concept / Structure Split
