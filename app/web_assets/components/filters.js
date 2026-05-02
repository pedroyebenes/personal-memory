// Filter strip: tags / aliases / vault path / modified date range.
// Reads from and writes back to `store.filters`. Used in chat, search, map, docs.

import { h } from "../lib/h.js";

function parseCsv(value) {
  return value.split(",").map((s) => s.trim()).filter(Boolean);
}

function isEmpty(filters) {
  if (!filters) return true;
  return (
    !(filters.tags && filters.tags.length) &&
    !(filters.aliases && filters.aliases.length) &&
    !filters.path_prefix &&
    !filters.date_from &&
    !filters.date_to
  );
}

export function buildFilters({ store, compact = false }) {
  const tagsInput    = h("input", { type: "text", placeholder: "project, planning" });
  const aliasesInput = h("input", { type: "text", placeholder: "North Star" });
  const pathInput    = h("input", { type: "text", placeholder: "books/ or projects/" });
  const fromInput    = h("input", { type: "date" });
  const toInput      = h("input", { type: "date" });

  function syncFromStore() {
    const f = store.get("filters") || {};
    tagsInput.value    = (f.tags || []).join(", ");
    aliasesInput.value = (f.aliases || []).join(", ");
    pathInput.value    = f.path_prefix || "";
    fromInput.value    = f.date_from || "";
    toInput.value      = f.date_to   || "";
    summary.dataset.empty = isEmpty(f) ? "true" : "false";
    summary.textContent = isEmpty(f) ? "No filters active." : describeFilters(f);
  }

  function pushToStore() {
    const next = {
      tags: parseCsv(tagsInput.value),
      aliases: parseCsv(aliasesInput.value),
      path_prefix: pathInput.value.trim() || null,
      date_from: fromInput.value || null,
      date_to:   toInput.value   || null,
    };
    store.set({ filters: next });
  }

  for (const inp of [tagsInput, aliasesInput, pathInput, fromInput, toInput]) {
    inp.addEventListener("change", pushToStore);
  }

  const clearBtn = h("button", {
    type: "button",
    class: "pm-chip pm-chip-muted",
    onclick: () => {
      store.set({ filters: { tags: [], aliases: [], path_prefix: null, date_from: null, date_to: null } });
    },
  }, "Clear");

  const summary = h("div", { class: "pm-active-filters", "data-empty": "true" }, "No filters active.");

  const grid = compact
    ? h("div", { class: "pm-section", style: { gap: "var(--pm-sp-2)" } }, [
        h("label", { class: "pm-field" }, [h("span", null, "Tags"),    tagsInput]),
        h("label", { class: "pm-field" }, [h("span", null, "Aliases"), aliasesInput]),
        h("label", { class: "pm-field" }, [h("span", null, "Vault path"), pathInput]),
        h("div", { class: "pm-field-row" }, [
          h("label", { class: "pm-field" }, [h("span", null, "From"), fromInput]),
          h("label", { class: "pm-field" }, [h("span", null, "To"),   toInput]),
        ]),
      ])
    : h("div", { class: "pm-section" }, [
        h("div", { class: "pm-field-row" }, [
          h("label", { class: "pm-field" }, [h("span", null, "Tags"),    tagsInput]),
          h("label", { class: "pm-field" }, [h("span", null, "Aliases"), aliasesInput]),
        ]),
        h("label", { class: "pm-field" }, [h("span", null, "Vault path"), pathInput]),
        h("div", { class: "pm-field-row" }, [
          h("label", { class: "pm-field" }, [h("span", null, "Modified from"), fromInput]),
          h("label", { class: "pm-field" }, [h("span", null, "Modified to"),   toInput]),
        ]),
      ]);

  const root = h("section", { class: "pm-section", "aria-label": "Filters" }, [
    h("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "baseline" } }, [
      h("div", { class: "pm-section-title" }, "Filters"),
      clearBtn,
    ]),
    grid,
    summary,
  ]);

  syncFromStore();
  const off = store.on("filters", syncFromStore);

  return { root, destroy() { off(); } };
}

function describeFilters(f) {
  const parts = [];
  if (f.tags?.length)    parts.push(`tags: ${f.tags.join(", ")}`);
  if (f.aliases?.length) parts.push(`aliases: ${f.aliases.join(", ")}`);
  if (f.path_prefix)     parts.push(`path: ${f.path_prefix}`);
  if (f.date_from || f.date_to) {
    parts.push(`modified ${f.date_from || "…"} → ${f.date_to || "…"}`);
  }
  return parts.join(" · ");
}

export function filtersAreActive(filters) {
  return !isEmpty(filters);
}
