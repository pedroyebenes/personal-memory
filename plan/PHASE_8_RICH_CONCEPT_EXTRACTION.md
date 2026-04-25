# Phase 8: Rich Concept Extraction

Objective:

- extract substantially more semantic concepts from note body text, not only document titles, headings, tags, aliases, and wikilinks

## Workstream

Primary workstream:

- richer deterministic and local concept discovery with mandatory chunk provenance

## Product Shape

The concept layer should surface meaningful ideas, names, projects, people, places, works, and recurring topics from any vault content:

- personal notes
- project notes
- meeting notes
- research notes
- daily notes
- imported books and long-form documents

Book support is useful, but Phase 8 should not be book-specific. The extraction pipeline should work across ordinary Markdown notes and long documents.

## Current Limitation

Phase 6 and Phase 7 extract concepts only from structured metadata and local Markdown structure:

- titles
- filenames
- headings
- tags
- aliases
- wikilinks

This misses concepts that appear only in body text, such as character names, organizations, people, recurring phrases, project names, technical terms, places, tools, and themes.

## Extraction Sources

Phase 8 should add body-text extraction sources while keeping every mention tied to a chunk:

- repeated capitalized phrases, such as `Project North Star`, `Don Quijote`, or `OpenAI API`
- explicit definitions, such as `X is ...`, `X means ...`, or `X: ...`
- Markdown emphasis used as term markers, such as `**term**` or `_term_`
- inline hashtags, such as `#research/llms`
- repeated noun-like phrases using a lightweight local heuristic
- optional local NER when an installed local library is available

Out of initial scope:

- cloud-only extraction
- uncited concepts
- concepts written without chunk provenance
- large ontology design

## Entity Types

Keep `entity_type = concept` for generic concepts, but prepare for more specific semantic types when evidence is strong:

- `person`
- `place`
- `organization`
- `project`
- `work`
- `event`
- `concept`
- `structure`

The first implementation can store all body-text candidates as `concept` unless a deterministic rule is clear.

## Quality Controls

Richer extraction can create noise, so Phase 8 needs safeguards:

- minimum phrase length for body candidates
- stopword and boilerplate filters
- reject phrases that are mostly punctuation or numbers
- reject common Markdown/UI terms unless repeated strongly
- require repeated evidence across chunks or a strong marker such as a definition/emphasis/wikilink/tag
- cap per-chunk extracted concepts to avoid flooding imported books
- keep structures excluded from concept-aware boosts

## Ranking and Promotion

Candidate concepts should carry extraction confidence in metadata or derived scoring:

- strong: wikilink, tag, alias, explicit definition
- medium: repeated capitalized phrase, emphasized term
- weak: noun-phrase heuristic

Default concept lists should show promoted concepts first. Low-confidence candidates can be hidden unless requested.

## Tasks

- add body-text candidate extraction to `app/processing/concepts.py`
- add extraction methods such as `body_phrase`, `definition`, `emphasis`, `inline_tag`, and `local_ner`
- add candidate quality filters and stoplists
- preserve chunk-level provenance for every body-text mention
- update refresh/reindex so body concepts rebuild deterministically
- add CLI/API filters for extraction method and entity type if needed
- update concept-aware retrieval to use only promoted semantic concepts
- add tests for repeated phrase extraction, definition extraction, stopword filtering, provenance, and refresh idempotency
- add fixtures that cover project notes, meeting notes, daily notes, and long-form/book content

## Exit Criteria

- a vault with ordinary prose produces concepts beyond titles/headings/tags/wikilinks
- body-text concepts include exact chunk/document provenance
- repeated meaningful phrases are extracted without flooding the database with one-off noise
- imported books produce people/places/works/themes when evidence is repeated or explicitly marked
- project and meeting notes produce project names, people, tools, and recurring topics
- `personal-memory concepts refresh` remains deterministic and idempotent
- tests cover non-book notes as well as long-form/book content
