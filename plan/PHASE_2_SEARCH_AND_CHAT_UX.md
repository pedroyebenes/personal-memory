# Phase 2: Search and Chat UX

Objective:

- make the web app easier to use for real note exploration

## Workstream

Primary workstream:

- search and chat usability

## Tasks

- add filter controls for tags, aliases, path prefixes, and date ranges
- extend `/api/search` and `/api/chat` payloads to accept filters
- surface active provider and model in the chat result panel
- add actionable source interactions such as copy path, open section reference, or deep-link hooks
- add recent query history and saved searches in the web UI
- improve refresh and status messaging in the sidebar

## Primary Files

- `app/web.py`
- `app/retrieval/hybrid_search.py`
- `app/retrieval/qa.py`
- possible schema/query helpers for metadata filters

## Dependencies

- Phase 1 for structured error handling

## Deliverables

- metadata filter controls in the UI
- provider/model visibility in responses
- actionable source cards
- recent queries and saved searches

## Exit Criteria

- users can narrow results without changing the plain-text query
- source cards are actionable rather than passive
- the active provider/model is always visible after a response
- refresh and status messages are clearer and more informative

## Milestone Focus

Milestone:

- Search Controls and Source Actions

## Implementation Status

Status:

- implemented metadata filters for tags, aliases, path prefixes, and modified date ranges
- wired filters through `/api/search` and `/api/chat`
- added provider/model visibility, actionable source cards, recent queries, saved searches, and clearer refresh/status messaging
- added regression coverage for metadata and date-range filter behavior
