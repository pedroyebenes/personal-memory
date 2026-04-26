# Phase 2: Viz Concept Surface

Objective:

- make the 3D embedding visualization display real concepts from the entity layer instead of chunk headings

## Workstream

Primary workstream:

- surface the existing `entities` / `entity_mentions` tables through the `/api/viz` payload and the Three.js frontend

## Current Limitation

Today each point's label is the chunk's Markdown heading:

```
# app/web_assets/viz.html
function conceptName(p) {
  if (p.section_title?.trim()) return p.section_title.trim();
  const words = p.snippet.trim().split(/\s+/);
  return words.slice(0, 6).join(' ') + (words.length > 6 ? '…' : '');
}
```

And `_compute_viz_data` in `app/web.py` never joins the concept tables:

```
SELECT c.id, c.text, c.section_title, d.id AS document_id, d.source_path,
       d.title AS document_title, e.vector_json
FROM chunks c
JOIN documents d ON c.document_id = d.id
JOIN embeddings e ON e.chunk_id = c.id
ORDER BY d.title, c.chunk_index
```

Cluster naming in `_cluster_name_from_rows` counts raw `section_title` / `document_title` values; the `_VIZ_STOP_TERMS` filter only touches capitalized body phrases, never titles. For book vaults this causes chapter names to dominate both per-point labels and cluster labels.

## Product Shape

- every point exposes a `top_concept` object (`id`, `canonical_name`, `method`) when at least one concept-typed entity is mentioned in its chunk
- clusters are named from concept mentions aggregated across their chunks, not from raw headings
- point text labels are removed; clusters and the legend carry the semantic narrative, tooltips and the pinned popover provide details on hover/click

## Extraction Sources For `top_concept`

In order of preference, breaking ties by `entities.mention_count`:

1. `wikilink`
2. `alias`
3. `tag`
4. `definition`
5. `inline_tag`
6. `emphasis`
7. `body_phrase`
8. `heading` (only as a last resort and only when `entity_type='concept'`)

Mentions whose `entity_type = 'structure'` are always excluded.

## Tasks

- extend `_compute_viz_data` to fetch, for each chunk, the best concept-typed `entity_mentions` row using the priority above; expose it on each point as `top_concept`
- collect all concept mentions for each cluster (set of chunks) and build cluster names from their `canonical_name` distribution; use the current capitalized-phrase fallback only when a cluster has no concept mentions at all
- in `app/web_assets/viz.html`:
  - delete `conceptName()` and all `.point-label` DOM wiring in `buildLabels()`, `refreshLabels()`, the label-layer SVG, and the sidebar "Labels" slider
  - keep tooltip, legend, pinned popover, and edges intact
  - populate tooltip `tt-concept` and popover `np-title` from `p.top_concept?.canonical_name ?? p.document_title`
  - update `searchableText(p)` to use `[p.top_concept?.canonical_name, p.document_title, p.snippet]`
- add a brief legend note explaining that point hover/double-click reveals concept and source details

## Primary Files

- `app/web.py`
- `app/web_assets/viz.html`
- `tests/test_web_viz.py` (new)

## Dependencies

- [Phase 1](./PHASE_1_STRUCTURE_FILTER_HARDENING.md) should land first so the concepts the viz surfaces are not polluted with chapter labels; Phase 2 can still ship on its own but will look cleaner once Phase 1 is in.

## Tests

- `_compute_viz_data` returns `top_concept` for chunks that have concept mentions and omits it otherwise
- cluster names are derived from concept mentions when present, not from raw section titles
- viz payload is stable across runs for a fixture vault

## Exit Criteria

- hovering a point in a book-heavy vault shows the concept, not the chapter name
- cluster legend entries are dominated by semantic concepts (people, places, themes) when those exist
- point-level text labels are gone; the sidebar "Labels" control is either repurposed or removed
- the viz endpoint keeps rendering for vaults that contain no concept mentions (purely structural vaults)

## Milestone Focus

Milestone:

- Concept-Aware Embedding Visualization
