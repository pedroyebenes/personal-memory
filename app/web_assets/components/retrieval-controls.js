// Retrieval controls: top-K, rerank, concept boost, LLM provider/model, query rewrite.
// Reads/writes `store.retrieval`. The chat view also reads `store.retrieval.useLlm`
// and the search view ignores it (search only retrieves).

import { h } from "../lib/h.js";

const PROVIDERS = [
  { value: "ollama", label: "Ollama" },
  { value: "gemini", label: "Gemini" },
  { value: "nvidia", label: "NVIDIA" },
  { value: "openai", label: "OpenAI" },
  { value: "mlx_lm", label: "MLX-LM" },
];

export function buildRetrievalControls({ store }) {
  const topK = h("input", { type: "number", min: "1", step: "1", value: "5" });
  const rerank = h("input", { type: "checkbox" });
  const conceptBoost = h("input", { type: "checkbox" });
  const useLlm = h("input", { type: "checkbox" });
  const rewrite = h("input", { type: "checkbox" });
  const provider = h("select", { "aria-label": "LLM provider" },
    PROVIDERS.map((p) => h("option", { value: p.value }, p.label)),
  );
  const model = h("input", { type: "text", placeholder: "Model name" });
  const providerStatus = h("div", { class: "pm-empty", style: { fontSize: "var(--pm-text-xs)" } }, "");

  function syncFromStore() {
    const r = store.get("retrieval") || {};
    if (r.topK != null) topK.value = String(r.topK);
    rerank.checked       = !!r.rerank;
    conceptBoost.checked = !!r.conceptBoost;
    useLlm.checked       = !!r.useLlm;
    rewrite.checked      = !!r.rewrite;
    if (r.provider) provider.value = r.provider;
    if (r.model != null) model.value = r.model;
  }

  function pushToStore() {
    const parsed = Number.parseInt(topK.value, 10);
    store.set({
      retrieval: {
        topK: Number.isFinite(parsed) && parsed >= 1 ? parsed : 5,
        rerank: rerank.checked,
        conceptBoost: conceptBoost.checked,
        useLlm: useLlm.checked,
        rewrite: rewrite.checked,
        provider: provider.value,
        model: model.value.trim() || null,
      },
    });
  }

  provider.addEventListener("change", () => {
    const defaults = store.get("providerDefaults") || {};
    model.value = defaults[provider.value] || "";
    pushToStore();
  });

  for (const inp of [topK, rerank, conceptBoost, useLlm, rewrite, model]) {
    inp.addEventListener("change", pushToStore);
    if (inp === model) inp.addEventListener("input", pushToStore);
  }

  const root = h("section", { class: "pm-section", "aria-label": "Retrieval" }, [
    h("div", { class: "pm-section-title" }, "Retrieval"),
    h("label", { class: "pm-field" }, [h("span", null, "Top K"), topK]),
    h("label", { class: "pm-toggle" }, [rerank, h("span", null, "Rerank")]),
    h("label", { class: "pm-toggle" }, [conceptBoost, h("span", null, "Concept boost")]),
    h("div", { class: "pm-field-row" }, [
      h("label", { class: "pm-field" }, [h("span", null, "Provider"), provider]),
      h("label", { class: "pm-field" }, [h("span", null, "Model"),    model]),
    ]),
    providerStatus,
    h("label", { class: "pm-toggle" }, [useLlm,  h("span", null, "LLM synthesis")]),
    h("label", { class: "pm-toggle" }, [rewrite, h("span", null, "Query rewrite")]),
  ]);

  syncFromStore();
  const off = store.on("retrieval", syncFromStore);

  return {
    root,
    setProviderStatus(text, kind = "muted") {
      providerStatus.textContent = text || "";
      providerStatus.classList.toggle("pm-error", kind === "error");
    },
    destroy() { off(); },
  };
}
