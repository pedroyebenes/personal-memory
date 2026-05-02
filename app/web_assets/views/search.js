import { h, mount, clear } from "../lib/h.js";
import { searchHybrid, listConcepts, getConcept, postEval } from "../lib/api.js";
import { loadRecents, pushRecent, loadSaved, saveSaved, deleteSaved } from "../lib/storage.js";
import { buildFilters } from "../components/filters.js";
import { buildRetrievalControls } from "../components/retrieval-controls.js";
import { buildEvidenceCard } from "../components/evidence-card.js";
import { formatScore } from "../lib/format.js";

const DEFAULT_EVAL_CASES = {
  cases: [
    { id: "north-star", query: "North Star launch",
      expected_paths: ["project-note.md"], expected_terms: ["launch"] },
  ],
};

export const searchView = {
  mount(target, { store }) {
    const filters = buildFilters({ store });
    const retrieval = buildRetrievalControls({ store });
    const rail = h("aside", { class: "pm-workbench-rail" }, [retrieval.root, filters.root]);

    const tabs = h("div", { class: "pm-subtabs", role: "tablist" });
    const panel = h("div", { class: "pm-section" });

    const main = h("section", { class: "pm-workbench-main" }, [tabs, panel]);
    target.appendChild(h("div", { class: "pm-workbench" }, [rail, main]));

    const subviews = {
      results:  buildResultsPane({ store }),
      concepts: buildConceptsPane({ store }),
      eval:     buildEvalPane({ store }),
    };

    const order = [
      ["results",  "Results"],
      ["concepts", "Concepts"],
      ["eval",     "Eval"],
    ];
    let active = "results";

    for (const [id, label] of order) {
      const btn = h("button", {
        type: "button",
        class: "pm-subtab",
        role: "tab",
        "data-sub": id,
        onclick: () => activate(id),
      }, label);
      tabs.appendChild(btn);
    }

    function activate(id) {
      active = id;
      for (const t of tabs.querySelectorAll(".pm-subtab")) {
        t.setAttribute("aria-selected", t.dataset.sub === id ? "true" : "false");
      }
      mount(panel, subviews[id].root);
      subviews[id].activate?.();
    }
    activate("results");

    this._cleanup = () => {
      filters.destroy?.();
      retrieval.destroy?.();
      for (const sv of Object.values(subviews)) sv.destroy?.();
    };
  },

  unmount() { this._cleanup?.(); },
};

// ── Results sub-pane ─────────────────────────────────────
function buildResultsPane({ store }) {
  const queryInput = h("input", { type: "search", placeholder: "Keyword or concept" });
  const goBtn = h("button", { class: "pm-primary", type: "submit" }, "Search");

  const form = h("form", { class: "pm-composer", onsubmit: (e) => { e.preventDefault(); run(); } }, [
    queryInput, goBtn,
  ]);

  const results = h("div", { style: { display: "flex", flexDirection: "column", gap: "var(--pm-sp-3)" } });
  const status = h("div", { class: "pm-empty" }, "No search yet — type a query above.");

  const recentsBlock = h("div", { class: "pm-section" });
  const savedBlock   = h("div", { class: "pm-section" });

  const root = h("section", { class: "pm-section" }, [form, status, results, savedBlock, recentsBlock]);

  function renderRecents() {
    const list = loadRecents();
    clear(recentsBlock);
    recentsBlock.appendChild(h("div", { class: "pm-section-title" }, `Recent (${list.length})`));
    if (!list.length) {
      recentsBlock.appendChild(h("div", { class: "pm-empty" }, "No recent queries yet."));
      return;
    }
    recentsBlock.appendChild(
      h("div", { class: "pm-active-filters" },
        list.map((q) =>
          h("button", {
            type: "button",
            class: "pm-chip pm-chip-muted",
            onclick: () => { queryInput.value = q; run(); },
          }, q),
        ),
      ),
    );
  }

  const saveNameInput = h("input", { type: "text", placeholder: "Save current as…" });
  const saveBtn = h("button", { type: "button", onclick: () => {
    const name = saveNameInput.value.trim();
    const q = queryInput.value.trim();
    if (!name || !q) return;
    saveSaved({ name, query: q, filters: store.get("filters"), retrieval: store.get("retrieval") });
    saveNameInput.value = "";
    renderSaved();
  } }, "Save");

  const savedList = h("div", { class: "pm-active-filters" });

  function renderSaved() {
    const list = loadSaved();
    clear(savedBlock);
    savedBlock.appendChild(h("div", { class: "pm-section-title" }, `Saved (${list.length})`));
    savedBlock.appendChild(h("div", { class: "pm-composer" }, [saveNameInput, saveBtn]));
    clear(savedList);
    savedBlock.appendChild(savedList);
    if (!list.length) {
      savedList.appendChild(h("div", { class: "pm-empty" }, "No saved searches."));
      return;
    }
    for (const e of list) {
      savedList.appendChild(
        h("span", { class: "pm-chip" }, [
          h("button", {
            type: "button",
            class: "pm-chip-x",
            style: { background: "transparent", color: "inherit", padding: 0, border: 0 },
            onclick: () => {
              queryInput.value = e.query;
              if (e.filters) store.set({ filters: e.filters });
              if (e.retrieval) store.set({ retrieval: e.retrieval });
              run();
            },
          }, e.name),
          h("button", {
            type: "button",
            class: "pm-chip-x",
            "aria-label": `Delete saved search ${e.name}`,
            onclick: () => { deleteSaved(e.name); renderSaved(); },
          }, "×"),
        ]),
      );
    }
  }

  async function run() {
    const query = queryInput.value.trim();
    if (!query) return;
    goBtn.disabled = true;
    status.textContent = "Searching…";
    clear(results);
    try {
      const r = store.get("retrieval") || {};
      const payload = await searchHybrid({
        query,
        topK: r.topK ?? 5,
        filters: store.get("filters"),
        rerank: r.rerank,
        conceptBoost: r.conceptBoost,
      });
      const items = payload.results || [];
      pushRecent(query);
      renderRecents();
      if (!items.length) {
        status.textContent = "No results.";
        return;
      }
      status.textContent = `${items.length} results`;
      const terms = query.split(/\s+/).filter((s) => s.length >= 2);
      for (const it of items) results.appendChild(buildEvidenceCard(it, { store, terms }));
    } catch (err) {
      status.className = "pm-error";
      status.textContent = `Search failed: ${err.message}`;
    } finally {
      goBtn.disabled = false;
    }
  }

  return {
    root,
    activate() {
      renderRecents();
      renderSaved();
      // Pre-populate from store query if present (e.g. from concept chip click).
      const seeded = store.get("query");
      if (seeded && !queryInput.value) queryInput.value = seeded;
      queryInput.focus();
    },
  };
}

// ── Concepts sub-pane ───────────────────────────────────
function buildConceptsPane({ store }) {
  const searchInput  = h("input", { type: "search", placeholder: "Filter concepts" });
  const typeSelect   = h("select", null, [
    h("option", { value: "concept" }, "Concepts"),
    h("option", { value: "structure" }, "Structures"),
    h("option", { value: "all" }, "All"),
  ]);
  const qualitySelect = h("select", null, [
    h("option", { value: "" }, "Any quality"),
    h("option", { value: "strong" }, "Strong"),
    h("option", { value: "medium" }, "Medium"),
    h("option", { value: "weak" }, "Weak"),
  ]);
  const methodInput = h("input", { type: "text", placeholder: "method: alias, tag, body_phrase" });
  const listBtn = h("button", { class: "pm-primary", type: "submit" }, "List");

  const form = h("form", { class: "pm-section", onsubmit: (e) => { e.preventDefault(); run(); } }, [
    h("div", { class: "pm-field-row" }, [searchInput, typeSelect]),
    h("div", { class: "pm-field-row" }, [qualitySelect, methodInput]),
    listBtn,
  ]);

  const list = h("div", { style: { display: "flex", flexDirection: "column", gap: "var(--pm-sp-2)" } });
  const detail = h("div");
  const root = h("section", { class: "pm-section" }, [form, list, detail]);

  async function run() {
    listBtn.disabled = true;
    clear(detail);
    list.replaceChildren(h("div", { class: "pm-empty" }, "Loading…"));
    try {
      const payload = await listConcepts({
        search: searchInput.value.trim() || undefined,
        type: typeSelect.value,
        limit: 50,
        quality: qualitySelect.value || undefined,
        method: methodInput.value.trim() || undefined,
      });
      const items = payload.concepts || [];
      clear(list);
      if (!items.length) {
        list.appendChild(h("div", { class: "pm-empty" }, "No concepts matched."));
        return;
      }
      for (const c of items) {
        const inspect = h("button", { type: "button", onclick: () => showDetail(c.id) }, "Inspect");
        const search = h("button", { type: "button", onclick: () => {
          store.set({ query: c.canonical_name });
          location.hash = "#/search";
        } }, "Search");
        list.appendChild(h("article", { class: "pm-evidence" }, [
          h("div", { class: "pm-evidence-head" }, [
            h("span", { class: "pm-evidence-title" }, c.canonical_name),
            h("span", { class: "pm-evidence-score" }, `${c.mention_count || 0} mentions`),
          ]),
          h("div", { class: "pm-evidence-meta" }, [
            h("span", null, `type: ${c.entity_type || "concept"}`),
            h("span", { style: { color: "var(--pm-fg-faint)" } }, "·"),
            h("span", null, `quality: ${c.quality || "unknown"}`),
            h("span", { style: { color: "var(--pm-fg-faint)" } }, "·"),
            h("span", null, `docs: ${c.document_count || 0}`),
          ]),
          h("div", { class: "pm-empty", style: { fontStyle: "normal" } }, `Methods: ${(c.extraction_methods || []).join(", ") || "none"}`),
          h("div", { class: "pm-evidence-actions" }, [inspect, search]),
        ]));
      }
    } catch (err) {
      clear(list);
      list.appendChild(h("div", { class: "pm-error" }, err.message));
    } finally {
      listBtn.disabled = false;
    }
  }

  async function showDetail(id) {
    if (!id) return;
    clear(detail);
    detail.appendChild(h("div", { class: "pm-empty" }, "Loading concept…"));
    try {
      const d = await getConcept(id);
      clear(detail);
      detail.appendChild(h("article", { class: "pm-card" }, [
        h("h2", null, d.canonical_name),
        h("div", { class: "pm-evidence-meta" }, [
          h("span", null, `type: ${d.entity_type || "concept"}`),
          h("span", { style: { color: "var(--pm-fg-faint)" } }, "·"),
          h("span", null, `quality: ${d.quality || "unknown"}`),
          h("span", { style: { color: "var(--pm-fg-faint)" } }, "·"),
          h("span", null, `mentions: ${d.mention_count || 0}`),
        ]),
        ...(d.top_chunks || []).slice(0, 5).map((c) =>
          buildEvidenceCard({
            document_title: c.document_title,
            source_path:    c.source_path,
            section_title:  c.section_title,
            snippet:        c.chunk_snippet,
            source_ref:     c.source_ref,
            markdown_ref:   c.markdown_ref,
            final_score:    null,
          }, { store }),
        ),
        h("div", { class: "pm-empty", style: { fontStyle: "normal" } },
          `Documents: ${(d.related_documents || []).map((x) => `${x.document_title} (${x.mention_count})`).join(" · ") || "none"}`),
      ]));
    } catch (err) {
      clear(detail);
      detail.appendChild(h("div", { class: "pm-error" }, err.message));
    }
  }

  return {
    root,
    activate() { /* lazy: only load on submit */ },
  };
}

// ── Eval sub-pane ───────────────────────────────────────
function buildEvalPane({ store }) {
  const cases = h("textarea", { rows: "10", spellcheck: "false" });
  cases.value = JSON.stringify(DEFAULT_EVAL_CASES, null, 2);

  const useRerank = h("input", { type: "checkbox" });
  const useConceptBoost = h("input", { type: "checkbox" });
  const runBtn = h("button", { class: "pm-primary", type: "submit" }, "Run checks");

  const form = h("form", { class: "pm-section", onsubmit: (e) => { e.preventDefault(); run(); } }, [
    cases,
    h("div", { class: "pm-active-filters" }, [
      h("label", { class: "pm-toggle" }, [useRerank, h("span", null, "Use rerank")]),
      h("label", { class: "pm-toggle" }, [useConceptBoost, h("span", null, "Use concept boost")]),
    ]),
    runBtn,
  ]);

  const results = h("div", { class: "pm-empty" }, "No checks have run.");
  const root = h("section", { class: "pm-section" }, [form, results]);

  async function run() {
    runBtn.disabled = true;
    results.className = "pm-empty";
    results.textContent = "Running…";
    try {
      const raw = cases.value.trim();
      const parsed = raw ? JSON.parse(raw) : DEFAULT_EVAL_CASES;
      const payload = await postEval({
        cases: Array.isArray(parsed) ? parsed : parsed.cases,
        top_k: store.get("retrieval")?.topK ?? 5,
        rerank: useRerank.checked,
        concept_boost: useConceptBoost.checked,
      });
      renderResults(payload);
    } catch (err) {
      results.className = "pm-error";
      results.textContent = `Eval failed: ${err.message}`;
    } finally {
      runBtn.disabled = false;
    }
  }

  function renderResults(payload) {
    clear(results);
    results.className = "pm-section";
    const summary = h("div", { class: "pm-section-title" },
      `${payload.status || "—"}: ${payload.passed || 0}/${payload.total || 0} passed`);
    results.appendChild(summary);
    for (const c of payload.cases || []) {
      results.appendChild(h("article", { class: "pm-evidence" }, [
        h("div", { class: "pm-evidence-head" }, [
          h("span", { class: "pm-evidence-title" }, `${c.ok ? "✓" : "✗"} ${c.id || "case"}`),
          h("span", { class: "pm-evidence-score" }, c.ok ? "pass" : "fail"),
        ]),
        h("div", { class: "pm-evidence-snippet" }, c.query),
        h("div", { class: "pm-evidence-meta" }, [
          h("span", null, `expected paths: ${(c.expected_paths || []).join(", ") || "none"}`),
          h("span", { style: { color: "var(--pm-fg-faint)" } }, "·"),
          h("span", null, `expected terms: ${(c.expected_terms || []).join(", ") || "none"}`),
        ]),
        h("div", { class: "pm-evidence-meta" }, [
          h("span", null, `top paths: ${(c.top_paths || []).slice(0, 3).join(" · ") || "none"}`),
        ]),
      ]));
    }
  }

  return {
    root,
    activate() {},
  };
}
