# Plan 2 Index

Concepts & Retrieval Overhaul — a follow-on plan born from a concrete bug: the 3D embedding visualization labels every point with its chapter/section heading instead of a real concept. Investigating the symptom surfaced a broader set of improvements across ingestion, concept quality, keyword/semantic retrieval, and storage.

This plan is self-contained. It assumes the work in `plan/` (Phases 1–8) is landed or in flight and extends that stack; it does not replace it.

## Symptom That Triggered the Plan

In `app/web_assets/viz.html`, each point's "concept" label is literally its chunk heading:

```
function conceptName(p) {
  if (p.section_title?.trim()) return p.section_title.trim();
  ...
}
```

The `_compute_viz_data` endpoint in `app/web.py` never touches `entities` / `entity_mentions`. So for a book vault every point reads as "Capítulo IV" and cluster names inherit the same bias. The `_STRUCTURAL_LABEL_PATTERNS` filter in `app/processing/concepts.py` is also too narrow to catch subtitled chapters, front-matter sections, and date-like headings, so structural labels still leak into the `concept` entity type.

## Scope

- Viz: stop using `section_title` as "concept"; route through `entities`/`entity_mentions`; leave points unlabeled and let clusters carry the semantics.
- Concepts: stronger structural classification, diacritic-folding normalization, dedup/merge on upsert.
- Chunking: heading-path breadcrumbs on chunks and in the embedded text.
- Retrieval: field-weighted BM25 on FTS5, exact-concept keyword boost.
- Storage: proper ANN vector index via `sqlite-vec` with JSON fallback retained.
- Optional: entity-level embeddings for concept-level semantic search and better cluster naming.
- Hygiene: incremental entity refresh per file, idempotent schema migrations, rebuild CLIs.

## Documents

- [TASKS.md](./TASKS.md): backlog and priority summary for this plan
- [PHASE_1_STRUCTURE_FILTER_HARDENING.md](./PHASE_1_STRUCTURE_FILTER_HARDENING.md): catch more structural labels before they become concepts
- [PHASE_2_VIZ_CONCEPT_SURFACE.md](./PHASE_2_VIZ_CONCEPT_SURFACE.md): route the visualization through real entity concepts
- [PHASE_3_CONCEPT_NORMALIZATION.md](./PHASE_3_CONCEPT_NORMALIZATION.md): diacritic fold and safe dedup on `normalize_key`
- [PHASE_4_BREADCRUMB_CHUNKS.md](./PHASE_4_BREADCRUMB_CHUNKS.md): heading-path breadcrumbs in chunks and embeddings
- [PHASE_5_INGEST_HYGIENE.md](./PHASE_5_INGEST_HYGIENE.md): incremental refresh, idempotent migrations, rebuild CLI
- [PHASE_6_WEIGHTED_FTS.md](./PHASE_6_WEIGHTED_FTS.md): field-weighted BM25 and exact-concept keyword boost
- [PHASE_7_VECTOR_INDEX.md](./PHASE_7_VECTOR_INDEX.md): add `sqlite-vec` ANN index with JSON fallback
- [PHASE_8_ENTITY_EMBEDDINGS.md](./PHASE_8_ENTITY_EMBEDDINGS.md): optional entity-level embeddings for concept semantic search

## Implementation Order

Phases are numbered in execution order. Phase 5 (Ingest Hygiene) is adjacent to Phase 4 because re-embedding after breadcrumbing requires its rebuild CLI; Phase 8 is optional polish and can be deferred.

1. [Phase 1](./PHASE_1_STRUCTURE_FILTER_HARDENING.md) — cheap, unblocks Phase 2
2. [Phase 2](./PHASE_2_VIZ_CONCEPT_SURFACE.md) — the visible fix the user asked for
3. [Phase 3](./PHASE_3_CONCEPT_NORMALIZATION.md) — raises concept quality for everything downstream
4. [Phase 4](./PHASE_4_BREADCRUMB_CHUNKS.md) — improves embeddings and FTS simultaneously
5. [Phase 5](./PHASE_5_INGEST_HYGIENE.md) — consolidates migrations/CLI, enables the re-embed path Phase 4 needs
6. [Phase 6](./PHASE_6_WEIGHTED_FTS.md) — small changes, noticeable wins
7. [Phase 7](./PHASE_7_VECTOR_INDEX.md) — required for larger vaults, defer if small
8. [Phase 8](./PHASE_8_ENTITY_EMBEDDINGS.md) — optional polish

## Planning Principles

- Preserve the local-first, inspectable SQLite core; every new index is derivable and rebuildable.
- Keep the existing `embeddings.vector_json` as the canonical source of truth; ANN lives alongside it.
- Deterministic behavior first; ML-heavy extras stay behind flags.
- Every schema change must migrate idempotently in `init_db` with an explicit rebuild CLI.
- Every phase must leave the app shippable even if later phases are deferred.

## Cross-Phase Risks

- Changing what gets embedded (Phase 4) invalidates stored vectors; requires a rebuild path (Phase 5).
- Adding `sqlite-vec` (Phase 7) must gracefully fall back when the extension isn't loadable (CI, older SQLite).
- Tightening structural classification (Phase 1) can drop concepts users relied on; include a one-shot migration that reclassifies existing rows without dropping mention provenance.
- Weighted BM25 (Phase 6) will change ranking; add a small golden-question evaluation before merging.

## Explicitly Deferred

- Automatic file watching / background sync (still deferred, as in `plan/`)
- Cross-document concept linking / relation tables
- LLM-assisted entity extraction
- Multi-vault support
