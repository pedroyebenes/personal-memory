// Small formatters used by multiple views.

export function formatScore(score) {
  if (score == null || Number.isNaN(score)) return "—";
  return score.toFixed(3);
}

export function formatPercent(value, digits = 0) {
  if (value == null || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatRelativeDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const diffMs = Date.now() - d.getTime();
  const day = 24 * 60 * 60 * 1000;
  if (diffMs < day) return "today";
  if (diffMs < 2 * day) return "yesterday";
  if (diffMs < 14 * day) return `${Math.floor(diffMs / day)}d ago`;
  return d.toISOString().slice(0, 10);
}

export function truncate(text, max = 240) {
  if (!text) return "";
  if (text.length <= max) return text;
  return text.slice(0, max - 1).trimEnd() + "…";
}

// Build a DocumentFragment with <mark> spans around matches of any term.
// Avoids innerHTML so it is safe to call with arbitrary text.
export function highlight(text, terms) {
  const frag = document.createDocumentFragment();
  if (!text) return frag;
  const cleanTerms = (terms || [])
    .map((t) => (typeof t === "string" ? t.trim() : ""))
    .filter((t) => t.length >= 2);
  if (!cleanTerms.length) {
    frag.appendChild(document.createTextNode(text));
    return frag;
  }
  const escaped = cleanTerms.map(escapeRegex).join("|");
  const re = new RegExp(`(${escaped})`, "gi");
  let last = 0;
  for (const m of text.matchAll(re)) {
    if (m.index > last) frag.appendChild(document.createTextNode(text.slice(last, m.index)));
    const mark = document.createElement("mark");
    mark.textContent = m[0];
    frag.appendChild(mark);
    last = m.index + m[0].length;
  }
  if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)));
  return frag;
}

function escapeRegex(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function obsidianUrl(vaultName, relPath) {
  if (!relPath) return null;
  const params = new URLSearchParams();
  if (vaultName) params.set("vault", vaultName);
  params.set("file", relPath.replace(/\.md$/, ""));
  return `obsidian://open?${params.toString()}`;
}
