// Evidence card — used in chat answers and search results.
//
// `result` matches the API shape from /api/search and citation entries in
// /api/chat: { document_title, source_path, section_title, snippet,
//              final_score, metadata_score, rerank_score, source_ref,
//              markdown_ref, matched_concepts, score_explanation }

import { h } from "../lib/h.js";
import { formatScore, highlight, truncate } from "../lib/format.js";

export function buildEvidenceCard(result, { store, terms = [] } = {}) {
  const title = result.document_title || "Untitled";
  const path = result.source_path || "";
  const snippet = truncate(result.snippet || "", 360);

  const titleEl = h("a", {
    class: "pm-evidence-title",
    href: "#/docs",
    onclick: (e) => {
      e.preventDefault();
      if (store && path) {
        store.set({ selectedDocumentPath: path });
        location.hash = "#/docs";
      }
    },
  }, title);

  const meta = [];
  if (result.section_title) {
    meta.push(h("span", null, result.section_title));
    meta.push(h("span", { style: { color: "var(--pm-fg-faint)" } }, "·"));
  }
  if (path) meta.push(h("span", { class: "pm-evidence-path" }, path));

  const concepts = (result.matched_concepts || []).slice(0, 3);
  for (const c of concepts) {
    meta.push(h("span", { style: { color: "var(--pm-fg-faint)" } }, "·"));
    meta.push(h("a", {
      class: "pm-chip pm-chip-muted",
      href: "#/graph",
      onclick: (e) => {
        e.preventDefault();
        if (store) {
          store.set({ selectedConceptId: c.id ?? null });
          location.hash = "#/graph";
        }
      },
    }, c.canonical_name || `Concept ${c.id}`));
  }

  const scoreLine = h("span", { class: "pm-evidence-score", title: scoreTooltip(result) },
    formatScore(result.final_score),
  );
  const head = h("div", { class: "pm-evidence-head" }, [titleEl, scoreLine]);

  const snippetEl = h("div", { class: "pm-evidence-snippet" });
  snippetEl.appendChild(highlight(snippet, terms));

  const sourceRef = result.source_ref || `${title} (${path})`;
  const markdownRef = result.markdown_ref || `> ${snippet}\n\n— ${sourceRef}`;

  const docsHref = path ? "#/docs" : null;
  const obsidianHref = path ? `obsidian://open?path=${encodeURIComponent(path)}` : null;

  const actions = h("div", { class: "pm-evidence-actions" }, [
    h("button", { type: "button", onclick: () => copy(path), title: "Copy path" }, "Copy path"),
    h("button", { type: "button", onclick: () => copy(sourceRef), title: "Copy source ref" }, "Copy ref"),
    h("button", { type: "button", onclick: () => copy(markdownRef), title: "Copy markdown" }, "Copy md"),
    docsHref && h("a", {
      href: docsHref,
      class: "pm-evidence-action-link",
      style: { color: "var(--pm-fg-muted)" },
      title: "Read in Docs",
      onclick: () => {
        if (store && path) store.set({ selectedDocumentPath: path });
      },
    }, "Read in Docs"),
    obsidianHref && h("a", { href: obsidianHref, class: "pm-evidence-action-link", style: { color: "var(--pm-fg-muted)" }, title: "Open in Obsidian" }, "↗ Obsidian"),
  ]);

  return h("article", { class: "pm-evidence" }, [
    head,
    h("div", { class: "pm-evidence-meta" }, meta),
    snippetEl,
    actions,
  ]);
}

function copy(text) {
  if (!text) return;
  navigator.clipboard?.writeText(text).catch(() => { /* ignore */ });
}

function scoreTooltip(r) {
  const parts = [];
  const ex = r.score_explanation || {};
  if (typeof ex.keyword_score === "number")  parts.push(`keyword ${ex.keyword_score.toFixed(3)}`);
  if (typeof ex.semantic_score === "number") parts.push(`semantic ${ex.semantic_score.toFixed(3)}`);
  if (typeof r.metadata_score === "number" && r.metadata_score > 0) parts.push(`metadata ${r.metadata_score.toFixed(3)}`);
  if (typeof r.rerank_score === "number" && r.rerank_score > 0)     parts.push(`rerank +${r.rerank_score.toFixed(3)}`);
  if (typeof ex.concept_boost === "number" && ex.concept_boost > 0) parts.push(`concept +${ex.concept_boost.toFixed(3)}`);
  return parts.join(" · ");
}
