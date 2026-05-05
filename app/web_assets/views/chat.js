import { h, clear } from "../lib/h.js";
import { getStatus, postChat } from "../lib/api.js";
import { loadWorkspaces, saveWorkspaces, pushRecent } from "../lib/storage.js";
import { buildFilters } from "../components/filters.js";
import { buildRetrievalControls } from "../components/retrieval-controls.js";
import { buildEvidenceCard } from "../components/evidence-card.js";

const ANSWER_PLACEHOLDER = "Ask a question to start a workspace.";
const HISTORY_TURN_LIMIT = 6;
const HISTORY_SOURCE_LIMIT = 5;

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
    const newThreadBtn = h("button", {
      class: "pm-chip pm-chip-muted",
      type: "button",
      onclick: () => startNewThread(),
    }, "New thread");

    const workspaceTabs = h("div", { class: "pm-workspaces", role: "tablist", "aria-label": "Answer workspaces" });
    const answerDetail = h("section", { class: "pm-card pm-empty" }, ANSWER_PLACEHOLDER);

    const composer = h("form", { class: "pm-composer", onsubmit: (e) => { e.preventDefault(); ask(); } }, [
      queryInput,
      h("div", { style: { display: "flex", gap: "var(--pm-sp-2)", alignItems: "center" } }, [askBtn, newThreadBtn]),
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
      const r = { ...(store.get("retrieval") || {}) };
      const filtersValue = { ...(store.get("filters") || {}) };
      const turn = createTurn({ query, filters: filtersValue, retrieval: r });
      let ws = normalizeWorkspace(activeWorkspace(store));
      if (!ws) {
        ws = createWorkspace({ turn, filters: filtersValue, retrieval: r });
        pushWorkspace(store, ws);
      } else {
        ws.turns = [...(ws.turns || []), turn];
        ws.retrieval = r;
        ws.filters = filtersValue;
        ws.status = "loading";
        ws.updated_at = new Date().toISOString();
        replaceWorkspace(store, ws);
      }
      queryInput.value = "";
      const history = buildHistoryPayload(ws, turn.id);
      try {
        const payload = await postChat({
          query,
          history,
          use_llm: !!r.useLlm,
          rewrite_query: !!r.rewrite,
          rerank: !!r.rerank,
          concept_boost: !!r.conceptBoost,
          top_k: r.topK ?? 5,
          provider: r.provider || "ollama",
          model: r.model || "",
          filters: filtersValue,
        });
        turn.status = "ready";
        turn.answer = payload.answer || "(no answer)";
        turn.answer_mode = payload.answer_mode || "";
        turn.sources = payload.sources || [];
        turn.retrieval_query = payload.retrieval_query || query;
        turn.provider = payload.provider || turn.provider;
        turn.model = payload.model || turn.model;
        turn.warnings = payload.warnings || [];
        ws.status = "ready";
        ws.updated_at = new Date().toISOString();
        pushRecent(query);
      } catch (err) {
        turn.status = "error";
        turn.answer = err.message || "Request failed.";
        turn.warnings = [turn.answer];
        ws.status = "error";
        ws.updated_at = new Date().toISOString();
      } finally {
        replaceWorkspace(store, ws);
        askBtn.disabled = false;
      }
    }

    function startNewThread() {
      store.set({ activeWorkspaceId: null });
      queryInput.focus();
    }

    function renderWorkspaceTabs() {
      const list = (store.get("workspaces") || []).map(normalizeWorkspace).filter(Boolean);
      const activeId = store.get("activeWorkspaceId");
      clear(workspaceTabs);
      if (!list.length) return;
      for (const ws of list) {
        const tab = h("button", {
          type: "button",
          class: "pm-workspace-tab",
          "aria-pressed": ws.id === activeId ? "true" : "false",
          onclick: () => store.set({ activeWorkspaceId: ws.id }),
          title: ws.title || ws.question,
        }, [
          h("span", { class: "pm-ws-label" }, ws.title || ws.question),
          h("span", { class: "pm-ws-status", style: { color: "var(--pm-fg-faint)" } }, statusGlyph(ws)),
        ]);
        workspaceTabs.appendChild(tab);
      }
    }

    function renderActiveWorkspace() {
      const ws = normalizeWorkspace(activeWorkspace(store));
      clear(answerDetail);
      answerDetail.classList.toggle("pm-empty", !ws);
      if (!ws) {
        answerDetail.appendChild(document.createTextNode(ANSWER_PLACEHOLDER));
        return;
      }
      const nodes = [
        h("div", { class: "pm-section" }, [
          h("div", { class: "pm-section-title" }, "Conversation"),
          h("div", { style: { fontSize: "var(--pm-text-lg)" } }, ws.title || ws.question),
        ]),
      ];
      for (const [index, turn] of (ws.turns || []).entries()) {
        nodes.push(...renderTurn(turn, index + 1));
      }
      answerDetail.append(...nodes);
    }

    function renderTurn(turn, index) {
      const terms = (turn.retrieval_query || turn.question || "").split(/\s+/).filter((s) => s.length >= 2);
      const questionBlock = h("div", { class: "pm-section" }, [
        h("div", { class: "pm-section-title" }, `Question ${index}`),
        h("div", { style: { fontSize: "var(--pm-text-lg)" } }, turn.question),
      ]);
      const answerBlock = h("div", { class: "pm-section" }, [
        h("div", { class: "pm-section-title" }, [
          turn.status === "loading" ? "Retrieving..." :
          turn.status === "error"   ? "Error" :
          turn.answer_mode === "llm_synthesis" ? "LLM answer" : "Extractive answer",
        ]),
        h("div", { style: { whiteSpace: "pre-wrap", lineHeight: "var(--pm-leading-loose)" } }, turn.answer || ""),
      ]);
      const metaItems = [
        h("span", null, `Top K: ${turn.retrieval?.topK ?? turn.top_k ?? "-"}`),
        h("span", { style: { color: "var(--pm-fg-faint)" } }, "."),
        h("span", null, `Rerank: ${turn.retrieval?.rerank ? "on" : "off"}`),
        h("span", { style: { color: "var(--pm-fg-faint)" } }, "."),
        h("span", null, `Concept boost: ${turn.retrieval?.conceptBoost ? "on" : "off"}`),
      ];
      if (turn.retrieval?.useLlm || turn.answer_mode === "llm_synthesis") {
        metaItems.unshift(
          h("span", null, `Provider: ${turn.provider || "-"}`),
          h("span", { style: { color: "var(--pm-fg-faint)" } }, "."),
          h("span", null, `Model: ${turn.model || "default"}`),
          h("span", { style: { color: "var(--pm-fg-faint)" } }, "."),
        );
      }
      const meta = h("div", { class: "pm-evidence-meta" }, metaItems);
      const sources = h("div", { class: "pm-section" }, [
        h("div", { class: "pm-section-title" }, `Evidence (${(turn.sources || []).length})`),
        turn.sources?.length
          ? h("div", { style: { display: "flex", flexDirection: "column", gap: "var(--pm-sp-3)" } },
              turn.sources.map((s) => buildEvidenceCard(s, { store, terms })))
          : h("div", { class: "pm-empty" }, "No evidence retrieved."),
      ]);
      const warnings = (turn.warnings || []).length
        ? h("div", { class: "pm-section" }, [
            h("div", { class: "pm-section-title pm-status-warning" }, `Warnings (${turn.warnings.length})`),
            h("div", null, turn.warnings.map((w) => h("div", { class: "pm-empty" }, w))),
          ])
        : null;
      return [questionBlock, answerBlock, meta, sources, ...(warnings ? [warnings] : [])];
    }
  },

  unmount() { this._cleanup?.(); },
};

function statusGlyph(workspace) {
  const ws = normalizeWorkspace(workspace);
  if (!ws) return "0";
  const latest = ws.turns?.[ws.turns.length - 1];
  if (latest?.status === "loading") return "⟳";
  if (latest?.status === "error") return "!";
  return `${(ws.turns || []).length}`;
}

function createTurn({ query, filters, retrieval }) {
  return {
    id: `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
    question: query,
    answer: "Retrieving evidence...",
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

function createWorkspace({ turn, filters, retrieval }) {
  return {
    id: `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
    title: turn.question,
    question: turn.question,
    status: turn.status,
    turns: [turn],
    filters,
    retrieval,
    provider: retrieval.provider || "ollama",
    model: retrieval.model || "",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
}

function normalizeWorkspace(ws) {
  if (!ws || typeof ws !== "object") return null;
  if (Array.isArray(ws.turns)) {
    const turns = ws.turns.filter((t) => t && typeof t === "object").map((t) => ({
      id: t.id || `${ws.id || Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
      question: t.question || t.query || ws.question || ws.query || "",
      answer: t.answer || t.response || "",
      status: t.status || "ready",
      answer_mode: t.answer_mode || t.mode || "",
      sources: Array.isArray(t.sources) ? t.sources : [],
      retrieval_query: t.retrieval_query || t.query || t.question || "",
      filters: t.filters || ws.filters || {},
      retrieval: t.retrieval || ws.retrieval || {},
      provider: t.provider || ws.provider || ws.retrieval?.provider || "ollama",
      model: t.model || ws.model || ws.retrieval?.model || "",
      warnings: Array.isArray(t.warnings) ? t.warnings : [],
      created_at: t.created_at || t.createdAt || ws.created_at || ws.createdAt || new Date().toISOString(),
    })).filter((t) => t.question || t.answer);
    return {
      ...ws,
      title: ws.title || ws.question || ws.query || turns[0]?.question || "Conversation",
      question: ws.question || ws.query || turns[0]?.question || "Conversation",
      status: ws.status || turns[turns.length - 1]?.status || "ready",
      turns,
    };
  }
  const question = ws.question || ws.query || "";
  const turn = {
    id: `${ws.id || Date.now()}-turn`,
    question,
    answer: ws.answer || ws.response || "",
    status: ws.status || "ready",
    answer_mode: ws.answer_mode || ws.mode || "",
    sources: Array.isArray(ws.sources) ? ws.sources : [],
    retrieval_query: ws.retrieval_query || question,
    filters: ws.filters || {},
    retrieval: ws.retrieval || {},
    provider: ws.provider || ws.retrieval?.provider || "ollama",
    model: ws.model || ws.retrieval?.model || "",
    warnings: Array.isArray(ws.warnings) ? ws.warnings : [],
    created_at: ws.created_at || ws.createdAt || new Date().toISOString(),
  };
  return {
    ...ws,
    title: ws.title || question || "Conversation",
    question: question || "Conversation",
    status: turn.status,
    turns: question || turn.answer ? [turn] : [],
  };
}

function pushWorkspace(store, ws) {
  const existing = (store.get("workspaces") || []).filter((item) => item.id !== ws.id);
  const list = [ws, ...existing].slice(0, 24);
  store.set({ workspaces: list, activeWorkspaceId: ws.id });
  saveWorkspaces(list);
}

function replaceWorkspace(store, ws) {
  const current = store.get("workspaces") || [];
  const list = current.some((w) => w.id === ws.id)
    ? current.map((w) => (w.id === ws.id ? ws : w))
    : [ws, ...current].slice(0, 24);
  store.set({ workspaces: list });
  saveWorkspaces(list);
}

function activeWorkspace(store) {
  const id = store.get("activeWorkspaceId");
  return (store.get("workspaces") || []).find((w) => w.id === id) || null;
}

function buildHistoryPayload(ws, pendingTurnId) {
  return (ws.turns || [])
    .filter((turn) => turn.id !== pendingTurnId && turn.status === "ready")
    .slice(-HISTORY_TURN_LIMIT)
    .map((turn) => ({
      question: compact(turn.question, 400),
      answer: compact(turn.answer, 1000),
      answer_mode: turn.answer_mode || "",
      sources: (turn.sources || []).slice(0, HISTORY_SOURCE_LIMIT).map(historySource),
    }));
}

function historySource(source) {
  return {
    document_id: source.document_id ?? null,
    document_title: compact(source.document_title, 180),
    source_path: compact(source.source_path, 260),
    section_title: compact(source.section_title, 180),
    chunk_id: source.chunk_id ?? "",
    snippet: compact(source.snippet, 400),
  };
}

function compact(value, limit) {
  const text = typeof value === "string" ? value.replace(/\s+/g, " ").trim() : "";
  if (text.length <= limit) return text;
  return text.slice(0, Math.max(0, limit - 3)).trimEnd() + "...";
}

function seedWorkspaces(store) {
  if (store.get("workspaces") != null) return;
  const stored = loadWorkspaces().map(normalizeWorkspace).filter(Boolean);
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
      providerOrder: status.llm_provider_order || [],
      supportedLlmProviders: status.supported_llm_providers || [],
    });
  } catch {
    store.set({
      retrieval: { topK: 5, rerank: false, conceptBoost: false, useLlm: false, rewrite: false, provider: "ollama", model: "" },
    });
  }
}
