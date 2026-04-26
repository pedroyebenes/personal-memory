# Phase 6: Concept and Entity Memory Layer

Objective:

- turn indexed chunks into an inspectable concept/entity layer with source provenance

## Workstream

Primary workstream:

- derived memory layer for concepts, entities, aliases, and mentions

## Product Shape

The concept layer should answer questions like:

- what concepts does the vault contain?
- where is this concept mentioned?
- what aliases or related labels point to the same concept?
- which chunks and documents support this concept?
- can retrieval boost results that mention a matching concept?

This layer should not replace chunk retrieval. It should sit above it as derived metadata, while preserving chunk IDs and source paths as the ground truth.

## Initial Scope

Use the existing tables first:

- `entities` stores canonical concepts/entities.
- `entity_mentions` stores mentions tied to `chunk_id`.

Add migrations only when the current schema cannot represent required provenance. Likely additions:

- extraction method, such as `wikilink`, `tag`, `heading`, `alias`, `filename`, or `manual`
- normalized key for deduplication
- optional alias table if `document_aliases` is not sufficient
- optional relation table after concept listing and mentions are working

## Extraction Sources

The first implementation is deterministic and local-only:

- Obsidian wikilinks
- frontmatter aliases
- tags
- headings and section titles
- filenames and document titles

Model-assisted extraction is explicitly out of scope for the first concept layer. It can be added later as an optional enhancement after deterministic extraction, listing, and provenance are reliable.

Any future model-assisted extraction must keep citations mandatory by writing mentions only when they can be tied to a specific chunk.

## Tasks

- define a `concepts` processing module that extracts candidate concepts from parsed documents and chunks
- normalize candidate labels into stable canonical keys
- populate `entities` and `entity_mentions` during ingest and reindex
- delete and rebuild mentions for changed documents without disturbing unrelated documents
- add `personal-memory concepts list`
- add `personal-memory concepts show --name <concept>` or `--id <id>`
- add `personal-memory concepts refresh` for rebuilding only the derived layer
- add tests for deterministic extraction, alias normalization, and mention provenance
- expose web API endpoints for listing concepts and fetching concept detail
- add concept-aware retrieval boosts after the data layer is reliable

## Primary Files

- `app/schema.sql`
- `app/ingest/register.py`
- `app/processing/`
- `app/cli.py`
- `app/web.py`
- `tests/`

Expected new files:

- `app/processing/concepts.py`
- `app/retrieval/concept_search.py`
- `tests/test_concepts.py`

## Dependencies

- Phase 1 for structured errors and safer refresh behavior
- Phase 3 for retrieval instrumentation and scoring changes
- Phase 5 is required for clearer ingest diagnostics and rebuild semantics
- Phase 4 is not required unless optional model-assisted concept extraction is added later

## Deliverables

- populated concept/entity tables
- CLI concept listing and detail inspection
- concept mention provenance back to chunks and documents
- deterministic rebuild behavior
- optional concept-aware retrieval ranking
- web API surface for concept exploration

## Exit Criteria

- a freshly indexed vault has non-empty concepts when it contains wikilinks, tags, headings, aliases, or repeated named concepts
- every concept detail response includes source chunks and document paths
- concept extraction can be rerun without duplicate entities or mentions
- search/ask can explain when a result was boosted because of a concept match
- tests cover changed-document refresh, full reindex, and concept listing

## Milestone Focus

Milestone:

- Inspectable Concepts With Provenance
