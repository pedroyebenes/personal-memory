# Plan Index

This folder contains the planning documents for future work on Personal Memory.

Scope:

- cover all currently planned backlog items
- exclude automatic file watching / background sync

## Documents

- [TASKS.md](./TASKS.md): backlog and high-level phase summary
- [PHASE_1_RELIABILITY.md](./PHASE_1_RELIABILITY.md): reliability and operational safety baseline
- [PHASE_2_SEARCH_AND_CHAT_UX.md](./PHASE_2_SEARCH_AND_CHAT_UX.md): search and chat usability improvements
- [PHASE_3_RETRIEVAL_QUALITY.md](./PHASE_3_RETRIEVAL_QUALITY.md): ranking, snippet, and chunking quality work
- [PHASE_4_LLM_PROVIDER_MATURITY.md](./PHASE_4_LLM_PROVIDER_MATURITY.md): provider maturity and advanced LLM features
- [PHASE_5_INGESTION_AND_SCALE.md](./PHASE_5_INGESTION_AND_SCALE.md): ingestion diagnostics, performance, and scale improvements
- [PHASE_6_CONCEPT_ENTITY_LAYER.md](./PHASE_6_CONCEPT_ENTITY_LAYER.md): concept/entity extraction, mention provenance, and concept-aware retrieval
- [PHASE_7_STRUCTURE_CONCEPT_SPLIT.md](./PHASE_7_STRUCTURE_CONCEPT_SPLIT.md): separate structural labels from semantic concepts

## Planning Principles

- preserve the local-first retrieval core
- keep extractive output as the safe fallback path
- improve reliability before expanding feature surface
- prefer inspectable SQLite-backed behavior over opaque subsystems
- phase work so each stage leaves the app more usable even if later phases are deferred

## Suggested Implementation Order

1. [Phase 1](./PHASE_1_RELIABILITY.md)
2. [Phase 2](./PHASE_2_SEARCH_AND_CHAT_UX.md)
3. [Phase 3](./PHASE_3_RETRIEVAL_QUALITY.md)
4. [Phase 5](./PHASE_5_INGESTION_AND_SCALE.md)
5. [Phase 6](./PHASE_6_CONCEPT_ENTITY_LAYER.md)
6. [Phase 7](./PHASE_7_STRUCTURE_CONCEPT_SPLIT.md)
7. [Phase 4](./PHASE_4_LLM_PROVIDER_MATURITY.md), optional unless LLM features are needed

## Cross-Phase Risks

- expanding the web payload contract too early may create rework if filters and provider controls are added ad hoc
- reranking and streaming can increase latency and complexity if introduced without instrumentation
- multi-vault support can complicate assumptions currently baked into pruning and refresh logic
- concept extraction can create noisy or duplicate concepts unless deterministic normalization is strict
- caching provider responses requires careful cache keys to avoid incorrect reuse

## Explicitly Deferred

- automatic file watching
- background worker architecture
- major UI redesign
- document-summary derived layers until core retrieval behavior stabilizes
