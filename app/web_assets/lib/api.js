// Thin wrappers around the JSON endpoints exposed by app/web.py.
// Every helper resolves to the parsed payload or throws an Error with the
// server-provided message.

async function unwrap(res) {
  let body = null;
  try { body = await res.json(); } catch { /* ignore */ }
  if (!res.ok || (body && body.ok === false)) {
    const msg = body?.error?.message || `${res.status} ${res.statusText}`;
    const err = new Error(msg);
    err.code = body?.error?.code;
    err.status = res.status;
    err.details = body?.error?.details;
    throw err;
  }
  return body;
}

export async function getStatus() {
  return unwrap(await fetch("/api/status"));
}

export async function getViz() {
  return unwrap(await fetch("/api/viz"));
}

export async function searchHybrid({ query, topK, filters, rerank, conceptBoost }) {
  const params = new URLSearchParams();
  params.set("query", query);
  if (topK != null) params.set("top_k", String(topK));
  if (rerank) params.set("rerank", "true");
  if (conceptBoost) params.set("concept_boost", "true");
  if (filters) {
    for (const tag of filters.tags || []) params.append("tags", tag);
    for (const alias of filters.aliases || []) params.append("aliases", alias);
    if (filters.path_prefix) params.set("path_prefix", filters.path_prefix);
    if (filters.date_from) params.set("date_from", filters.date_from);
    if (filters.date_to) params.set("date_to", filters.date_to);
  }
  return unwrap(await fetch(`/api/search?${params.toString()}`));
}

export async function postChat(payload) {
  return unwrap(await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }));
}

export async function postRefresh() {
  return unwrap(await fetch("/api/refresh", { method: "POST" }));
}

export async function getRefreshStatus() {
  return unwrap(await fetch("/api/refresh-status"));
}

export async function listConcepts({ search, type, limit, quality, method } = {}) {
  const params = new URLSearchParams();
  if (search) params.set("search", search);
  if (type)   params.set("type", type);
  if (limit)  params.set("limit", String(limit));
  if (quality) params.set("quality", quality);
  if (method)  params.set("method", method);
  return unwrap(await fetch(`/api/concepts?${params.toString()}`));
}

export async function searchConcepts(query) {
  const url = new URL("/api/concepts/search", location.origin);
  url.searchParams.set("q", query);
  return unwrap(await fetch(url));
}

export async function getConcept(id) {
  return unwrap(await fetch(`/api/concepts/${encodeURIComponent(id)}`));
}

export async function getDocument(id) {
  return unwrap(await fetch(`/api/documents/${encodeURIComponent(id)}`));
}

export async function listDocuments() {
  return unwrap(await fetch("/api/documents"));
}

export async function getConceptGraph({ limit, minCooccurrence, edgeLimit } = {}) {
  const params = new URLSearchParams();
  if (limit != null)            params.set("limit", String(limit));
  if (minCooccurrence != null)  params.set("min_cooccurrence", String(minCooccurrence));
  if (edgeLimit != null)        params.set("edge_limit", String(edgeLimit));
  const qs = params.toString();
  return unwrap(await fetch(qs ? `/api/concepts/graph?${qs}` : "/api/concepts/graph"));
}

export async function postEval(payload) {
  return unwrap(await fetch("/api/eval/retrieval", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }));
}
