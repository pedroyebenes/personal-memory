import { h, mount } from "../lib/h.js";
import { getStatus, postRefresh, getRefreshStatus } from "../lib/api.js";
import { applyTheme, toggleTheme, loadTheme } from "../lib/theme.js";

const POLL_MS = 5000;

export function buildStatusBar({ store }) {
  const stats = h("div", { class: "pm-status-stats" }, "Loading…");
  const warning = h("span", { class: "pm-status-warning", hidden: true });

  const themeBtn = h("button", {
    type: "button",
    class: "pm-status-refresh",
    title: "Toggle theme",
    "aria-label": "Toggle theme",
    onclick: () => {
      const next = toggleTheme();
      themeBtn.textContent = next === "light" ? "☾" : "☀";
      themeBtn.setAttribute("aria-label", next === "light" ? "Switch to dark theme" : "Switch to light theme");
      store?.set({ theme: next });
    },
  });
  const initial = loadTheme();
  applyTheme(initial);
  themeBtn.textContent = initial === "light" ? "☾" : "☀";
  themeBtn.setAttribute("aria-label", initial === "light" ? "Switch to dark theme" : "Switch to light theme");

  const refreshBtn = h("button", {
    type: "button",
    class: "pm-status-refresh",
    onclick: triggerRefresh,
  }, "Refresh");

  const root = h("div", { class: "pm-status-bar", role: "status" }, [
    stats, warning, themeBtn, refreshBtn,
  ]);

  let pollTimer = null;
  let inProgress = false;

  function renderStatus(payload) {
    if (!payload) return;
    const items = [];
    const docs = payload.documents ?? payload.document_count;
    const chunks = payload.chunks ?? payload.chunk_count;
    const cov = payload.embeddings_coverage ?? payload.embedding_coverage;
    if (typeof docs === "number") {
      items.push(h("span", { class: "pm-status-item" }, [h("strong", null, docs.toLocaleString()), " docs"]));
    }
    if (typeof chunks === "number") {
      items.push(h("span", { class: "pm-status-sep" }, "·"));
      items.push(h("span", { class: "pm-status-item" }, [h("strong", null, chunks.toLocaleString()), " chunks"]));
    }
    if (typeof cov === "number") {
      items.push(h("span", { class: "pm-status-sep" }, "·"));
      items.push(h("span", { class: "pm-status-item" }, [h("strong", null, `${(cov * 100).toFixed(0)}%`), " embedded"]));
    }
    mount(stats, ...items);
    if (store) {
      const provider = payload.default_llm_provider || payload.llm_provider || "ollama";
      const patch = {
        status: payload,
        providerDefaults: payload.provider_defaults || {},
        providerAvailability: payload.provider_availability || {},
        providerOrder: payload.llm_provider_order || [],
      };
      if (!store.get("retrieval")) {
        patch.retrieval = {
          topK: payload.top_k ?? 5,
          rerank: !!payload.enable_reranking,
          conceptBoost: !!payload.enable_concept_boost,
          useLlm: false,
          rewrite: false,
          provider,
          model: payload.provider_defaults?.[provider] || "",
        };
      }
      store.set(patch);
    }
  }

  function renderWarning(text) {
    if (text) {
      warning.textContent = text;
      warning.hidden = false;
    } else {
      warning.hidden = true;
      warning.textContent = "";
    }
  }

  function setRefreshing(state) {
    inProgress = state;
    refreshBtn.disabled = state;
    refreshBtn.textContent = state ? "Refreshing…" : "Refresh";
  }

  async function poll() {
    try {
      const status = await getStatus();
      renderStatus(status);
      const rs = await getRefreshStatus().catch(() => null);
      if (rs?.in_progress) {
        setRefreshing(true);
      } else if (inProgress) {
        setRefreshing(false);
        if (rs?.last_result?.warnings?.length) {
          renderWarning(rs.last_result.warnings[0]);
        } else {
          renderWarning(null);
        }
      }
    } catch (err) {
      renderWarning(`Status: ${err.message}`);
    }
  }

  async function triggerRefresh() {
    if (inProgress) return;
    setRefreshing(true);
    try {
      await postRefresh();
    } catch (err) {
      renderWarning(err.message);
      setRefreshing(false);
    }
    poll();
  }

  function start() {
    poll();
    pollTimer = setInterval(poll, POLL_MS);
  }
  function stop() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
  }

  return { root, start, stop };
}
