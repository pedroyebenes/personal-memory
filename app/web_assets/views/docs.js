import { h, mount, clear } from "../lib/h.js";
import { listDocuments, getDocument } from "../lib/api.js";
import { buildFilters } from "../components/filters.js";
import { renderMarkdown } from "../lib/markdown.js";
import { buildRsvpReader } from "./rsvp.js";

let rsvpMode = false;
let activeRsvpDestroy = null;

export const docsView = {
  mount(target, { store }) {
    const filters = buildFilters({ store, compact: true });

    const search = h("input", { type: "search", placeholder: "Filter by path or title" });
    const treeBox = h("div", { class: "pm-section",
      style: { overflowY: "auto", flex: "1", minHeight: 0 } });

    const rail = h("aside", {
      class: "pm-workbench-rail",
      style: { display: "flex", flexDirection: "column", gap: "var(--pm-sp-3)" },
    }, [
      h("div", { class: "pm-section" }, [h("div", { class: "pm-section-title" }, "Filter"), filters.root]),
      search,
      treeBox,
    ]);

    const reader = h("section", { class: "pm-workbench-main" }, [
      h("div", { class: "pm-empty" }, "Select a document from the tree to read it."),
    ]);

    target.appendChild(h("div", { class: "pm-workbench" }, [rail, reader]));

    let documents = [];
    let selectedPath = store.get("selectedDocumentPath") || null;

    (async () => {
      mount(treeBox, h("div", { class: "pm-empty" }, "Loading vault…"));
      try {
        const payload = await listDocuments();
        documents = payload.documents || [];
        renderTree();
        if (selectedPath) openByPath(selectedPath);
      } catch (err) {
        mount(treeBox, h("div", { class: "pm-error" }, err.message));
      }
    })();

    function applyDocFilters(docs) {
      const f = store.get("filters") || {};
      const path = (f.path_prefix || "").trim();
      const q = search.value.trim().toLowerCase();
      return docs.filter((d) => {
        const displayPath = docTreePath(d);
        if (path && !d.source_path.startsWith(path) && !displayPath.startsWith(path)) return false;
        if (q && !`${d.title} ${displayPath} ${d.source_path}`.toLowerCase().includes(q)) return false;
        return true;
      });
    }

    function renderTree() {
      const filtered = applyDocFilters(documents);
      const tree = buildTree(filtered);
      clear(treeBox);
      treeBox.appendChild(h("div", { class: "pm-section-title" }, `${filtered.length.toLocaleString()} documents`));
      treeBox.appendChild(renderNode(tree, ""));
    }

    function renderNode(node, prefix) {
      const wrap = h("div", { style: { display: "flex", flexDirection: "column", gap: "1px" } });
      const childKeys = Object.keys(node.children).sort();
      for (const key of childKeys) {
        const child = node.children[key];
        const fullPath = prefix ? `${prefix}/${key}` : key;
        if (child.doc) {
          const isActive = selectedPath === child.doc.source_path;
          const displayPath = docTreePath(child.doc);
          wrap.appendChild(h("button", {
            type: "button",
            class: "pm-legend-item" + (isActive ? " active" : ""),
            style: { paddingLeft: "var(--pm-sp-2)", fontSize: "var(--pm-text-sm)" },
            title: child.doc.source_path === displayPath ? displayPath : `${displayPath}\n${child.doc.source_path}`,
            onclick: () => openDoc(child.doc),
          }, [
            h("span", { class: "pm-legend-text" }, [
              h("span", { class: "pm-legend-name" }, child.doc.title || key),
              h("span", { class: "pm-legend-count" }, `${child.doc.chunk_count} chunks`),
            ]),
          ]));
        } else {
          const summary = h("summary", {
            style: { cursor: "pointer", padding: "2px 4px", fontSize: "var(--pm-text-xs)",
                     color: "var(--pm-fg-muted)", listStyle: "none" },
          }, `▸ ${key}/`);
          const folder = h("details", {}, [summary, renderNode(child, fullPath)]);
          folder.style.marginLeft = "var(--pm-sp-2)";
          wrap.appendChild(folder);
        }
      }
      return wrap;
    }

    function buildTree(docs) {
      const root = { children: {}, doc: null };
      for (const d of docs) {
        const parts = docTreePath(d).split("/").filter(Boolean);
        let node = root;
        for (let i = 0; i < parts.length; i++) {
          const part = parts[i];
          if (!node.children[part]) node.children[part] = { children: {}, doc: null };
          node = node.children[part];
          if (i === parts.length - 1) node.doc = d;
        }
      }
      return root;
    }

    async function openDoc(d) {
      selectedPath = d.source_path;
      store.set({ selectedDocumentPath: d.source_path, selectedDocumentId: d.document_id });
      renderTree();
      activeRsvpDestroy?.();
      activeRsvpDestroy = null;
      mount(reader,
        h("div", { class: "pm-section" }, [
          h("div", { class: "pm-section-title" }, "Loading document…"),
        ]),
      );
      try {
        const doc = await getDocument(d.document_id);
        const obsidianHref = `obsidian://open?path=${encodeURIComponent(d.source_path)}`;
        const displayPath = doc.vault_relative_path || d.vault_relative_path || d.source_path;

        const readBtn = h("button", { type: "button", class: rsvpMode ? "pm-chip pm-chip-muted" : "pm-chip",
          onclick: () => { rsvpMode = false; openDoc(d); },
        }, "Read");
        const rsvpBtn = h("button", { type: "button", class: rsvpMode ? "pm-chip" : "pm-chip pm-chip-muted",
          onclick: () => { rsvpMode = true; openDoc(d); },
        }, "RSVP");

        let contentEl;
        if (rsvpMode) {
          const docList = applyDocFilters(documents);
          const docIdx = docList.findIndex(x => x.document_id === d.document_id);
          const built = buildRsvpReader(doc.raw_text, d.document_id, {
            onClose: () => { rsvpMode = false; openDoc(d); },
            onPrev: docIdx > 0 ? () => openDoc(docList[docIdx - 1]) : null,
            onNext: docIdx < docList.length - 1 ? () => openDoc(docList[docIdx + 1]) : null,
          });
          activeRsvpDestroy = built.destroy;
          contentEl = built.el;
        } else {
          contentEl = renderMarkdown(doc.raw_text || "");
        }

        mount(reader,
          h("section", { class: "pm-section" }, [
            h("div", { class: "pm-section-title" }, "Document"),
            h("h2", null, doc.title || d.title),
            h("div", { class: "pm-evidence-meta" }, [
              h("span", { class: "pm-evidence-path", title: doc.source_path || d.source_path }, displayPath),
              h("span", { style: { color: "var(--pm-fg-faint)" } }, "·"),
              h("span", null, `${d.chunk_count} chunks`),
              h("span", { style: { color: "var(--pm-fg-faint)" } }, "·"),
              h("a", { href: obsidianHref, class: "pm-chip pm-chip-muted" }, "Open in Obsidian ↗"),
              h("button", { type: "button", class: "pm-chip pm-chip-muted",
                onclick: () => {
                  store.set({ filters: { ...(store.get("filters") || {}), path_prefix: pathPrefix(displayPath) } });
                  location.hash = "#/chat";
                },
              }, "Use as filter"),
              readBtn,
              rsvpBtn,
            ]),
            contentEl,
          ]),
        );
      } catch (err) {
        mount(reader, h("div", { class: "pm-error" }, err.message));
      }
    }

    function openByPath(path) {
      const d = documents.find((x) => x.source_path === path || x.vault_relative_path === path);
      if (d) openDoc(d);
    }

    function pathPrefix(path) {
      const parts = (path || "").split("/").filter(Boolean);
      parts.pop(); // drop filename
      if (!parts.length) return "";
      // Keep the nearest folders so filters stay readable.
      return parts.slice(-2).join("/") + "/";
    }

    function docTreePath(d) {
      return d.vault_relative_path || d.source_path || "";
    }

    search.addEventListener("input", renderTree);
    const offFilters = store.on("filters", renderTree);
    const offSel = store.on("selectedDocumentPath", (path) => {
      if (path && path !== selectedPath) openByPath(path);
    });

    this._cleanup = () => {
      activeRsvpDestroy?.();
      activeRsvpDestroy = null;
      offFilters();
      offSel();
      filters.destroy?.();
    };
  },

  unmount() { this._cleanup?.(); },
};
