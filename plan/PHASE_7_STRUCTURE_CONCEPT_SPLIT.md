# Phase 7: Structure and Concept Split

Objective:

- separate navigational document structure from semantic concepts while preserving provenance

## Workstream

Primary workstream:

- concept quality and noise reduction for the derived memory layer

## Product Shape

The concept layer should default to semantic concepts that are useful for retrieval and inspection.
Structural labels should still be available for navigation and provenance, but they should not pollute
the primary concept list or concept-aware retrieval boosts.

Examples of structural labels:

- `CAPÍTULO XL`
- `Chapter 4`
- pure numeric headings such as `2`
- daily-note dates such as `2026-04-20`

Examples of semantic concepts:

- tags
- wikilinks
- frontmatter aliases
- meaningful document titles and section titles

## Tasks

- classify extracted mentions with an `entity_type` of `concept` or `structure`
- treat obvious chapter/date/number headings, titles, and filenames as `structure`
- keep tags, aliases, and wikilinks as semantic concepts
- make `personal-memory concepts list` default to semantic concepts only
- add a CLI option to list structures when needed
- make `/api/concepts` default to semantic concepts and accept a `type` filter
- keep concept-aware retrieval boosts limited to semantic concepts
- add tests for classification, listing filters, API filters, and boost behavior

## Exit Criteria

- `CAPÍTULO XL` no longer appears in the default concept list after a concept refresh
- `personal-memory concepts list --type structure` can show structural labels
- `/api/concepts?type=structure` can show structural labels
- concept-aware retrieval does not boost on structural labels
- concept detail still preserves chunk/document provenance for both concepts and structures
