import { h, mount, clear } from "../lib/h.js";
import { getStatus, postChat } from "../lib/api.js";
import { loadWorkspaces, saveWorkspaces, pushRecent } from "../lib/storage.js";
import { buildFilters } from "../components/filters.js";
import { buildRetrievalControls } from "../components/retrieval-controls.js";
import { buildEvidenceCard } from "../components/evidence-card.js";

const ANSWER_PLACEHOLDER = "Ask a question to start a workspace.";

export const chatView = {
  mount(target, { store }) {
    seedRetrievalDefaults(store);
    seedWorkspaces(store);

    const filters = buildFilters({ store });
    const retrieval = buildRetrievalControls({ store });

    const rail = h("aside", { class: "pm-workbench-rail" }, [retrieval.root, filters.root]);

    const queryInput = h("textarea", {
      placeholder: "What do my notes say about retrieval, a project, or a person?",
      rows: "3",
    });
    const askBtn = h("button", { class: "pm-primary", type: "submit" }, "Ask");

    const workspaceTabs = h("div", { class: "pm-workspaces", role: "tablist", "aria-label": "Answer workspaces" });
    const answerDetail = h("section", { class: "pm-card pm-empty" }, ANSWER_PLACEHOLDER);

    const composer = h("form", { class: "pm-composer", onsubmit: (e) => { e.preventDefault(); ask(); } }, [
      queryInput, askBtn,
    ]);

    const main = h("section", { class: "pm-workbench-main" }, [composer, workspaceTabs, answerDetail]);

    target.appendChild(h("div", { class: "pm-workbench" }, [rail, main]));

    renderWorkspaceTabs();
    renderActiveWorkspace();

    const off = store.onMany(["activeWorkspaceId", "workspaces"], () => {
      renderWorkspaceTabs();
      renderActiveWorkspace();
    });

    this._cleanup = () => {
      off();
      filters.destroy?.();
      retrieval.destroy?.();
    };

    async function ask() {
      const query = queryInput.value.trim();
      if (!query) return;
      askBtn.disabled = true;
      const r = store.get("retrieval") || {};
      const filtersValue = store.get("filters") || {};
      const ws = createWorkspace({ query, filters: filtersValue, retrieval: r });
      pushWorkspace(store, ws);
      queryInput.value = "";
      try {
        const payload = await postChat({
          query,
          use_llm: !!r.useLlm,
          rewrite_query: !!r.rewrite,
          rerank: !!r.rerank,
          concept_boost: !!r.conceptBoost,
          top_k: r.topK ?? 5,
          provider: r.provider || "ollama",
          model: r.model || "",
          filters: filtersValue,
        });
        ws.status = "ready";
        ws.answer = payload.answer || "(no answer)";
        ws.answer_mode = payload.answer_mode || "";
        ws.sources = payload.sources || [];
        ws.retrieval_query = payload.retrieval_query || query;
        ws.provider = payload.provider || ws.provider;
        ws.model = payload.model || ws.model;
        ws.warnings = payload.warnings || [];
        pushRecent(query);
      } catch (err) {
        ws.status = "error";
        ws.answer = err.message || "Request failed.";
        ws.warnings = [ws.answer];
      } finally {
        replaceWorkspace(store, ws);
        askBtn.disabled = false;
      }
    }

    function renderWorkspaceTabs() {
      const list = store.get("workspaces") || [];
      const activeId = store.get("activeWorkspaceId");
      clear(workspaceTabs);
      if (!list.length) return;
      for (const ws of list) {
        const tab = h("button", {
          type: "button",
          class: "pm-workspace-tab",
          "aria-pressed": ws.id === activeId ? "true" : "false",
          onclick: () => store.set({ activeWorkspaceId: ws.id }),
          title: ws.question,
        }, [
          h("span", { class: "pm-ws-label" }, ws.question),
          h("span", { class: "pm-ws-status", style: { color: "var(--pm-fg-faint)" } }, statusGlyph(ws)),
        ]);
        workspaceTabs.appendChild(tab);
      }
    }

    function renderActiveWorkspace() {
      const ws = activeWorkspace(store);
      clear(answerDetail);
      answerDetail.classList.toggle("pm-empty", !ws);
      if (!ws) {
        answerDetail.appendChild(document.createTextNode(ANSWER_PLACEHOLDER));
        return;
      }
      const terms = (ws.retrieval_query || ws.question || "").split(/\s+/).filter((s) => s.length >= 2);
      const head = h("div", { class: "pm-section" }, [
        h("div", { class: "pm-section-title" }, "Question"),
        h("div", { style: { fontSize: "var(--pm-text-lg)" } }, ws.question),
      ]);
      const answerBlock = h("div", { class: "pm-section" }, [
        h("div", { class: "pm-section-title" }, [
          ws.status === "loading" ? "Retrieving…" :
          ws.status === "error"   ? "Error" :
          ws.answer_mode === "llm_synthesis" ? "LLM answer" : "Extractive answer",
        ]),
        h("div", { style: { whiteSpace: "pre-wrap", lineHeight: "var(--pm-leading-loose)" } }, ws.answer || ""),
      ]);
      const metaItems = [
        h("span", null, `Top K: ${ws.retrieval?.topK ?? ws.top_k ?? "—"}`),
        h("span", { style: { color: "var(--pm-fg-faint)" } }, "·"),
        h("span", null, `Rerank: ${ws.retrieval?.rerank ? "on" : "off"}`),
        h("span", { style: { color: "var(--pm-fg-faint)" } }, "·"),
        h("span", null, `Concept boost: ${ws.retrieval?.conceptBoost ? "on" : "off"}`),
      ];
      if (ws.retrieval?.useLlm || ws.answer_mode === "llm_synthesis") {
        metaItems.unshift(
          h("span", null, `Provider: ${ws.provider || "—"}`),
          h("span", { style: { color: "var(--pm-fg-faint)" } }, "·"),
          h("span", null, `Model: ${ws.model || "default"}`),
          h("span", { style: { color: "var(--pm-fg-faint)" } }, "·"),
        );
      }
      const meta = h("div", { class: "pm-evidence-meta" }, metaItems);
      const sources = h("div", { class: "pm-section" }, [
        h("div", { class: "pm-section-title" }, `Evidence (${(ws.sources || []).length})`),
        ws.sources?.length
          ? h("div", { style: { display: "flex", flexDirection: "column", gap: "var(--pm-sp-3)" } },
              ws.sources.map((s) => buildEvidenceCard(s, { store, terms })))
          : h("div", { class: "pm-empty" }, "No evidence retrieved."),
      ]);
      const warnings = (ws.warnings || []).length
        ? h("div", { class: "pm-section" }, [
            h("div", { class: "pm-section-title pm-status-warning" }, `Warnings (${ws.warnings.length})`),
            h("div", null, ws.warnings.map((w) => h("div", { class: "pm-empty" }, w))),
          ])
        : null;
      answerDetail.append(head, answerBlock, meta, sources, ...(warnings ? [warnings] : []));
    }
  },

  unmount() { this._cleanup?.(); },
};

function statusGlyph(ws) {
  if (ws.status === "loading") return "⟳";
  if (ws.status === "error")   return "!";
  return `${(ws.sources || []).length}`;
}

function createWorkspace({ query, filters, retrieval }) {
  return {
    id: `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
    question: query,
    answer: "Retrieving evidence…",
    status: "loading",
    answer_mode: "",
    sources: [],
    retrieval_query: "",
    filters,
    retrieval,
    provider: retrieval.provider || "ollama",
    model: retrieval.model || "",
    warnings: [],
    created_at: new Date().toISOString(),
  };
}

function pushWorkspace(store, ws) {
  const list = [ws, ...(store.get("workspaces") || [])].slice(0, 24);
  store.set({ workspaces: list, activeWorkspaceId: ws.id });
  saveWorkspaces(list);
}

function replaceWorkspace(store, ws) {
  const list = (store.get("workspaces") || []).map((w) => (w.id === ws.id ? ws : w));
  store.set({ workspaces: list });
  saveWorkspaces(list);
}

function activeWorkspace(store) {
  const id = store.get("activeWorkspaceId");
  return (store.get("workspaces") || []).find((w) => w.id === id) || null;
}

function seedWorkspaces(store) {
  if (store.get("workspaces") != null) return;
  const stored = loadWorkspaces();
  store.set({
    workspaces: stored,
    activeWorkspaceId: stored[0]?.id || null,
  });
}

let statusSeeded = false;
async function seedRetrievalDefaults(store) {
  if (statusSeeded) return;
  statusSeeded = true;
  if (store.get("retrieval")) return;
  try {
    const status = await getStatus();
    store.set({
      retrieval: {
        topK: status.top_k ?? 5,
        rerank: !!status.enable_reranking,
        conceptBoost: !!status.enable_concept_boost,
        useLlm: false,
        rewrite: false,
        provider: status.default_llm_provider || status.llm_provider || "ollama",
        model: status.provider_defaults?.[status.default_llm_provider || status.llm_provider || "ollama"] || "",
      },
      providerDefaults: status.provider_defaults || {},
      providerAvailability: status.provider_availability || {},
    });
  } catch {
    store.set({
      retrieval: { topK: 5, rerank: false, conceptBoost: false, useLlm: false, rewrite: false, provider: "ollama", model: "" },
    });
  }
}
