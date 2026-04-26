# Phase 3: Retrieval Quality

Objective:

- improve answer relevance before adding more LLM complexity

## Workstream

Primary workstream:

- retrieval quality improvements

## Tasks

- add metadata-aware ranking features using tags, aliases, headings, filenames, and recency
- improve snippet extraction around relevant spans rather than broad chunk excerpts
- improve chunking for lists, callouts, code blocks, and other note structures
- add optional reranking after hybrid retrieval
- add retrieval debug output or developer mode instrumentation

## Primary Files

- `app/processing/chunker.py`
- `app/retrieval/keyword_search.py`
- `app/retrieval/semantic_search.py`
- `app/retrieval/hybrid_search.py`
- `app/retrieval/qa.py`
- retrieval and chunking tests

## Dependencies

- none

## Deliverables

- metadata-aware ranking signals
- tighter snippets
- improved chunking behavior
- optional reranking stage
- retrieval debug mode

## Exit Criteria

- result relevance improves on realistic vault queries
- snippets are more precise and readable
- developers can inspect why a result ranked the way it did

## Milestone Focus

Milestone:

- Better Ranking and Snippets
