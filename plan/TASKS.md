# Task List

This file captures the next improvement areas for Personal Memory and turns them into an implementation plan.

Excluded for now:

- automatic file watching / background sync

## Priority Summary

Priority order:

1. Reliability and operational safety
2. Search and chat usability
3. Retrieval quality
4. Ingestion performance and extensibility
5. Concept/entity memory layer
6. Local reference quality and concept inspection
7. Optional LLM/provider controls

## Backlog

### Reliability

- Add structured API errors across all web endpoints so the UI can distinguish configuration issues, provider failures, and ingestion failures.
- Add provider health checks beyond simple key presence.
- Add refresh job state and locking so overlapping index refresh requests cannot corrupt state or confuse the UI.
- Add startup/config validation with explicit diagnostics for missing keys, invalid provider names, and unreachable paths.
- Expand automated tests for web endpoints, provider selection, model override behavior, and refresh flows.

### Search and Chat UX

- Add search and chat filters for tags, path prefixes, aliases, and date ranges.
- Make source results actionable, such as deep-linking to a file/heading or providing a copyable source reference.
- Display active provider and model more clearly in the chat response area.
- Add recent queries and saved searches.
- Add visible ingestion progress and better reporting for partial refresh failures.

### Retrieval Quality

- Add metadata-aware ranking using tags, aliases, headings, filenames, and recency.
- Improve snippet extraction so returned evidence is tighter and easier to read.
- Improve chunking for lists, callouts, code blocks, and other Obsidian-heavy structures.
- Add optional reranking after hybrid retrieval.
- Add retrieval debug output to inspect why a result ranked well.

### LLM and Provider Layer

- Separate provider defaults for answer synthesis and query rewriting.
- Add per-provider request options such as temperature, max tokens, and timeout where applicable.
- Add streaming responses in the web chat.
- Add response caching for repeated query rewrite and synthesis requests when inputs match.
- Add fallback behavior, such as provider failure falling back to extractive output or a secondary provider.

### Ingestion and Data Handling

- Track richer ingest diagnostics, including failed file count and per-file errors.
- Use filesystem metadata alongside content hashes to reduce unnecessary reads for large vaults.
- Support richer YAML/frontmatter normalization and validation.
- Add multi-vault support or scoped vault mounts.

### Concept and Entity Memory Layer

- Add a derived concept extraction step that runs after chunking and embedding.
- Populate `entities` and `entity_mentions` from deterministic Obsidian structure first: wikilinks, aliases, tags, headings, section titles, filenames, and document titles.
- Add concept normalization so repeated names, aliases, and casing variants resolve to stable canonical concepts.
- Track concept-to-chunk provenance so every concept can be traced back to exact source chunks.
- Add CLI commands and web endpoints to list concepts, inspect mentions, and search by concept.
- Add concept-aware retrieval signals so queries can boost chunks that mention matching or related concepts.

### Local Reference Quality

- Add retrieval evaluation against local golden questions.
- Expose ranking diagnostics and matched concepts in search/ask results.
- Add concept quality and extraction-method filters.
- Add noise reports for low-value concept candidates.
- Improve concept details with top chunks, related documents, and copyable source references.

## Implementation Plan

### Phase 1: Reliability Baseline

Goal:
- make refresh, search, and chat behavior predictable under failure

Tasks:
- standardize API error payloads for `status`, `search`, `refresh`, and `chat`
- add refresh-state protection to prevent concurrent refresh runs
- return explicit UI messages for provider/configuration failures
- add tests for refresh conflicts, invalid provider selection, and missing credentials

Definition of done:
- the UI no longer shows generic network failures for normal backend errors
- duplicate refresh clicks cannot trigger overlapping ingest jobs
- test coverage exists for the major failure paths

### Phase 2: Better Search and Chat UX

Goal:
- make the web app easier to use for real note exploration

Tasks:
- add filter controls for tags, path prefixes, aliases, and date ranges
- show provider/model metadata in the response panel
- add clickable or copyable source references
- add recent queries and saved searches
- improve status and refresh feedback in the sidebar

Definition of done:
- a user can narrow results without editing the raw query
- source cards are actionable rather than passive
- the active provider/model is always visible

### Phase 3: Retrieval Quality Improvements

Goal:
- improve answer relevance before adding more UI complexity

Tasks:
- add metadata-aware scoring features
- improve chunking for structured note content
- improve snippet extraction around matched evidence
- add optional reranking stage
- expose retrieval debugging info for development

Definition of done:
- top results are more relevant on realistic vault queries
- snippets are shorter and more precise
- retrieval ranking changes can be inspected during development

### Phase 4: LLM Layer Maturity

Goal:
- make multi-provider operation more robust and controllable; this phase is optional for the deterministic concept layer

Tasks:
- split rewrite-model defaults from synthesis-model defaults
- add provider-specific generation settings
- add streaming chat responses
- add caching for repeated rewrite/synthesis requests
- add fallback strategies for synthesis failures

Definition of done:
- rewrite and synthesis can be tuned independently
- chat can stream responses when the provider supports it
- repeated requests avoid unnecessary provider calls

### Phase 5: Ingestion and Scale Improvements

Goal:
- improve performance and resilience for larger vaults without background watchers

Tasks:
- track per-file ingest failures and expose them in UI/CLI output
- use filesystem metadata to reduce unnecessary file work
- strengthen frontmatter normalization and validation
- evaluate multi-vault support or better vault scoping
- prepare rebuild semantics for derived layers such as concepts and mentions

Definition of done:
- large vault refreshes are more transparent and efficient
- malformed frontmatter does not break indexing
- ingestion reports clearly explain what succeeded and failed
- changed-document and full-vault rebuild semantics are clear enough for derived layers to reuse

### Phase 6: Concept and Entity Memory Layer

Goal:
- add an inspectable derived layer that turns chunks into durable concepts/entities with provenance

Tasks:
- define concept extraction inputs and outputs around the existing `entities` and `entity_mentions` tables
- implement deterministic extraction from Obsidian structure first: wikilinks, aliases, tags, headings, and filenames
- normalize aliases and duplicate mentions into canonical `entities`
- record mention text, source chunk, extraction source, and timestamps
- add `concepts` CLI commands for listing concepts, showing mentions, and refreshing the derived layer
- expose concept list/detail endpoints for the web UI
- feed concept matches back into retrieval ranking and source explanations

Definition of done:
- `personal-memory concepts list` can show extracted concepts with mention counts
- every concept mention links back to a chunk and document
- reindexing can rebuild the concept layer deterministically
- concept matches can improve retrieval without replacing chunk-level provenance
- no LLM or cloud provider is required for the first concept layer

### Phase 7: Structure and Concept Split

Goal:
- reduce concept-list noise by separating structural document labels from semantic concepts

Tasks:
- classify deterministic mentions as `concept` or `structure`
- treat obvious chapter/date/number headings, titles, and filenames as structure
- keep tags, aliases, and wikilinks as semantic concepts
- make concept listing default to semantic concepts while supporting structure filters
- limit retrieval boosts to semantic concepts

Definition of done:
- chapter headings such as `CAPÍTULO XL` are hidden from the default concept list
- structures remain inspectable through CLI/API filters
- search boost explanations only reference semantic concept matches

### Phase 8: Rich Concept Extraction

Goal:
- extract substantially more semantic concepts from note body text, not only document titles, headings, tags, aliases, and wikilinks

Tasks:
- extract body-text candidates from repeated capitalized phrases, explicit definitions, Markdown emphasis, and inline hashtags
- keep every body-text mention tied to a chunk
- filter structural labels, stopwords, boilerplate, and one-off noise
- keep extraction deterministic and local

Definition of done:
- ordinary prose produces concepts beyond document structure
- imported books and long-form documents produce repeated people, places, works, and themes when evidence is strong enough
- `personal-memory concepts refresh` remains deterministic and idempotent

### Phase 9: Local Reference Quality

Goal:
- make the project stronger as a local-first vault reference system by improving trust, inspection, and concept usefulness

Tasks:
- add `personal-memory eval retrieval` for local golden-question checks
- expose score explanations, matched concepts, source refs, and Markdown refs in search/ask payloads
- add concept filters for extraction method and quality
- add `personal-memory concepts noise-report`
- add concept detail top chunks and related documents
- update README/API docs for current concept and retrieval tooling

Definition of done:
- retrieval quality can be checked locally against explicit expected sources
- ranking behavior is visible without reading database rows manually
- concept lists can be narrowed to strong semantic concepts or specific extraction methods
- noisy candidates can be reviewed separately from normal concept browsing

## Recommended Starting Order

If implementation starts immediately, use this sequence:

1. Refresh job locking and structured API errors
2. Web endpoint tests for refresh/search/chat
3. Search filters and source actions
4. Provider/model visibility in responses
5. Metadata-aware ranking and snippet improvements
6. Better chunking and optional reranking
7. Ingestion diagnostics and large-vault optimizations
8. Concept/entity extraction from Obsidian metadata and chunk text
9. Concept listing, detail views, and retrieval boosts
10. Structure/concept split for concept quality
10. Rewrite-vs-synthesis model separation
11. Streaming and caching

## Explicitly Deferred

Not part of the current plan:

- automatic file watching
- background worker architecture
- major UI redesign
- document-summary derived layers until core retrieval behavior stabilizes
