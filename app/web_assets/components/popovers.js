// Draggable, resizable, maximizable popovers used by the map view (note + cluster).

import { h, clear } from "../lib/h.js";
import { loadPref, savePref } from "../lib/storage.js";
import { getDocument } from "../lib/api.js";

const FONT_KEY = "viz/popover-font";
const FONT_MIN = 0.7, FONT_MAX = 1.5, FONT_STEP = 0.1;

let fontScale = clampFontScale(loadPref(FONT_KEY, 1));

function clampFontScale(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return 1;
  return Math.min(FONT_MAX, Math.max(FONT_MIN, Math.round(n * 100) / 100));
}

function applyFontScale(els) {
  for (const el of els) if (el) el.style.setProperty("--np-font-scale", String(fontScale));
  savePref(FONT_KEY, fontScale);
}

function nudgeFont(els, delta) {
  fontScale = clampFontScale(fontScale + delta);
  applyFontScale(els);
}

// ── Drag + maximize wiring ─────────────────────────
export function makeDraggable(popover, handle) {
  if (!popover || !handle) return;
  let startX = 0, startY = 0, origLeft = 0, origTop = 0, dragging = false;

  function onMove(e) {
    if (!dragging) return;
    const dx = e.clientX - startX;
    const dy = e.clientY - startY;
    const rect = popover.getBoundingClientRect();
    const minVisible = 80;
    const maxX = window.innerWidth - minVisible;
    const minX = minVisible - rect.width;
    const maxY = window.innerHeight - 40;
    popover.style.left = `${Math.max(minX, Math.min(maxX, origLeft + dx))}px`;
    popover.style.top  = `${Math.max(0, Math.min(maxY, origTop + dy))}px`;
  }
  function onUp() {
    if (!dragging) return;
    dragging = false;
    popover.classList.remove("dragging");
    window.removeEventListener("mousemove", onMove);
    window.removeEventListener("mouseup", onUp);
  }

  handle.addEventListener("mousedown", (e) => {
    if (e.button !== 0) return;
    if (e.target.closest("button, input, textarea, a")) return;
    if (popover.classList.contains("maximized")) return;
    const rect = popover.getBoundingClientRect();
    origLeft = rect.left;
    origTop = rect.top;
    startX = e.clientX;
    startY = e.clientY;
    popover.style.left = `${origLeft}px`;
    popover.style.top  = `${origTop}px`;
    popover.style.right = "auto";
    popover.style.transform = "none";
    dragging = true;
    popover.classList.add("dragging");
    e.preventDefault();
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  });
}

function anchorAbsolutely(el) {
  if (!el || el.classList.contains("maximized")) return;
  const rect = el.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const margin = 8;
  el.style.left = `${Math.max(margin, Math.min(window.innerWidth - rect.width - margin, rect.left))}px`;
  el.style.top  = `${Math.max(margin, Math.min(window.innerHeight - rect.height - margin, rect.top))}px`;
  el.style.right = "auto";
  el.style.transform = "none";
}

function resetPosSize(el) {
  el.style.left = ""; el.style.top = ""; el.style.right = ""; el.style.transform = "";
  el.style.width = ""; el.style.height = "";
}

// ── Note popover ──────────────────────────────────
export function buildNotePopover() {
  const fontSmaller = h("button", { type: "button", class: "pm-popover-icon-btn pm-popover-font-btn", title: "Smaller text" }, "A−");
  const fontLarger  = h("button", { type: "button", class: "pm-popover-icon-btn pm-popover-font-btn", title: "Larger text" },  "A+");
  const maxBtn      = h("button", { type: "button", class: "pm-popover-icon-btn", "aria-pressed": "false", title: "Maximize" }, "⤢");
  const closeBtn    = h("button", { type: "button", class: "pm-popover-close", "aria-label": "Close" }, "×");
  const titleEl = h("div", { class: "pm-popover-title" });
  const head = h("div", { class: "pm-popover-head" }, [
    h("div", { class: "pm-popover-title-wrap" }, [titleEl]),
    h("div", { class: "pm-popover-actions" }, [fontSmaller, fontLarger, maxBtn, closeBtn]),
  ]);

  const docLine = h("div", { class: "pm-np-doc" });
  const pathLine = h("div", { class: "pm-np-path" });
  const snippet = h("div", { class: "pm-np-text" });
  const readBtn = h("button", { type: "button", class: "pm-np-read-btn" }, "Read full note");
  const fullStatus = h("div", { class: "pm-np-full-status", hidden: true });
  const fullPre = h("pre", { class: "pm-np-full-text", hidden: true });
  const fullBlock = h("div", { class: "pm-np-full" }, [fullStatus, fullPre]);

  const body = h("div", { class: "pm-popover-body" }, [
    docLine, pathLine,
    h("div", { class: "pm-np-snippet-label" }, "Excerpt"), snippet,
    h("div", { class: "pm-np-read-row" }, [readBtn]),
    fullBlock,
  ]);

  const root = h("div", { class: "pm-popover", role: "dialog", "aria-label": "Note details" }, [head, body]);

  let docId = null;
  let fullExpanded = false;
  let maximized = false;
  let opened = false;
  const cache = new Map();

  function reset() {
    fullBlock.classList.remove("open");
    fullStatus.hidden = true; fullStatus.textContent = "";
    fullStatus.className = "pm-np-full-status";
    fullPre.hidden = true; fullPre.textContent = "";
    readBtn.textContent = "Read full note";
    readBtn.disabled = false;
    fullExpanded = false;
  }

  function open(p) {
    reset();
    docId = p.document_id ?? null;
    titleEl.textContent = (p.top_concept?.canonical_name?.trim()) || (p.document_title || "Untitled");
    docLine.textContent = p.document_title || "";
    if (p.source_path) {
      pathLine.textContent = p.source_path;
      pathLine.style.display = "";
    } else {
      pathLine.textContent = ""; pathLine.style.display = "none";
    }
    snippet.textContent = p.snippet || "";
    if (docId == null) {
      readBtn.disabled = true;
      readBtn.title = "Document id missing — refresh after updating the app";
    } else {
      readBtn.disabled = false;
      readBtn.title = "";
    }
    setMax(false);
    resetPosSize(root);
    root.classList.add("open");
    anchorAbsolutely(root);
    opened = true;
  }

  function close() {
    root.classList.remove("open");
    setMax(false);
    opened = false;
    docId = null;
    reset();
  }

  function setMax(v) {
    maximized = v;
    resetPosSize(root);
    root.classList.toggle("maximized", v);
    if (!v && root.classList.contains("open")) anchorAbsolutely(root);
    maxBtn.setAttribute("aria-pressed", v ? "true" : "false");
    maxBtn.setAttribute("aria-label", v ? "Restore note panel size" : "Maximize note panel");
    maxBtn.textContent = v ? "⤡" : "⤢";
  }

  async function toggleFull() {
    if (docId == null) return;
    if (fullExpanded) {
      fullBlock.classList.remove("open");
      fullExpanded = false;
      readBtn.textContent = "Read full note";
      return;
    }
    fullBlock.classList.add("open");
    fullExpanded = true;
    readBtn.textContent = "Hide full note";
    if (cache.has(docId)) {
      fullPre.textContent = cache.get(docId);
      fullPre.hidden = false;
      fullStatus.hidden = true;
      return;
    }
    fullPre.hidden = true;
    fullStatus.hidden = false;
    fullStatus.className = "pm-np-full-status";
    fullStatus.textContent = "Loading…";
    readBtn.disabled = true;
    try {
      const data = await getDocument(docId);
      const raw = data.raw_text ?? "";
      cache.set(docId, raw);
      fullPre.textContent = raw;
      fullPre.hidden = false;
      fullStatus.hidden = true;
    } catch (e) {
      fullStatus.className = "pm-np-full-status pm-np-full-error";
      fullStatus.textContent = e.message || "Could not load note.";
    } finally {
      readBtn.disabled = false;
    }
  }

  fontSmaller.addEventListener("click", () => nudgeFont([root], -FONT_STEP));
  fontLarger .addEventListener("click", () => nudgeFont([root],  FONT_STEP));
  maxBtn   .addEventListener("click", () => setMax(!maximized));
  closeBtn .addEventListener("click", close);
  readBtn  .addEventListener("click", toggleFull);
  applyFontScale([root]);
  makeDraggable(root, head);

  return { root, open, close, isOpen: () => opened };
}

// ── Cluster popover ───────────────────────────────
export function buildClusterPopover({ onSelectPoint, onClose }) {
  const fontSmaller = h("button", { type: "button", class: "pm-popover-icon-btn pm-popover-font-btn", title: "Smaller text" }, "A−");
  const fontLarger  = h("button", { type: "button", class: "pm-popover-icon-btn pm-popover-font-btn", title: "Larger text" },  "A+");
  const maxBtn      = h("button", { type: "button", class: "pm-popover-icon-btn", "aria-pressed": "false", title: "Maximize" }, "⤢");
  const closeBtn    = h("button", { type: "button", class: "pm-popover-close", "aria-label": "Close" }, "×");
  const titleEl = h("div", { class: "pm-popover-title" });
  const subEl   = h("div", { class: "pm-popover-sub" });
  const head = h("div", { class: "pm-popover-head" }, [
    h("div", { class: "pm-popover-title-wrap" }, [titleEl, subEl]),
    h("div", { class: "pm-popover-actions" }, [fontSmaller, fontLarger, maxBtn, closeBtn]),
  ]);

  const termsWrap = h("div", { class: "pm-cp-chips" });
  const docsWrap  = h("div");
  const repsWrap  = h("div");

  const termsSection = h("div", { class: "pm-cp-section" }, [
    h("div", { class: "pm-cp-section-label" }, "Distinctive concepts"), termsWrap,
  ]);
  const docsSection = h("div", { class: "pm-cp-section" }, [
    h("div", { class: "pm-cp-section-label" }, "Top documents"), docsWrap,
  ]);
  const repsSection = h("div", { class: "pm-cp-section" }, [
    h("div", { class: "pm-cp-section-label" }, "Representative excerpts"), repsWrap,
  ]);

  const body = h("div", { class: "pm-popover-body" }, [termsSection, docsSection, repsSection]);
  const root = h("div", { class: "pm-popover", role: "dialog", "aria-label": "Cluster details" }, [head, body]);

  let maximized = false;

  function setMax(v) {
    maximized = v;
    resetPosSize(root);
    root.classList.toggle("maximized", v);
    if (!v && root.classList.contains("open")) anchorAbsolutely(root);
    maxBtn.setAttribute("aria-pressed", v ? "true" : "false");
    maxBtn.textContent = v ? "⤡" : "⤢";
  }

  function open(summary, vizData) {
    titleEl.textContent = summary.name || `Cluster ${summary.id + 1}`;
    const subParts = [`${summary.size.toLocaleString()} chunk${summary.size === 1 ? "" : "s"}`];
    if (typeof summary.coherence === "number") subParts.push(`coherence ${(summary.coherence * 100).toFixed(0)}%`);
    if (summary.is_noise) subParts.push("unclassified");
    subEl.replaceChildren();
    subParts.forEach((p, i) => {
      if (i > 0) subEl.appendChild(h("span", { class: "pm-dot" }, "•"));
      subEl.appendChild(document.createTextNode(p));
    });

    clear(termsWrap);
    const terms = Array.isArray(summary.terms) ? summary.terms : [];
    termsSection.style.display = terms.length ? "" : "none";
    for (const t of terms) termsWrap.appendChild(h("span", { class: "pm-cp-chip" }, t));

    clear(docsWrap);
    const docs = Array.isArray(summary.top_documents) ? summary.top_documents : [];
    docsSection.style.display = docs.length ? "" : "none";
    for (const d of docs) {
      docsWrap.appendChild(h("button", {
        type: "button", class: "pm-cp-doc",
        onclick: () => {
          const point = vizData.points.find((p) => p.document_id === d.document_id);
          if (point) onSelectPoint?.({ kind: "focus", index: vizData.points.indexOf(point) });
        },
      }, [
        h("span", { class: "pm-cp-doc-title" }, d.title || "Untitled"),
        h("span", { class: "pm-cp-doc-count" }, `${d.count} chunk${d.count === 1 ? "" : "s"}`),
      ]));
    }

    clear(repsWrap);
    const reps = Array.isArray(summary.representatives) ? summary.representatives : [];
    repsSection.style.display = reps.length ? "" : "none";
    for (const r of reps) {
      repsWrap.appendChild(h("button", {
        type: "button", class: "pm-cp-rep",
        onclick: () => {
          const point = vizData.points.find((p) => p.id === r.chunk_id);
          if (point) onSelectPoint?.({ kind: "open", point });
        },
      }, [
        h("span", { class: "pm-cp-rep-title" }, r.document_title || "Untitled"),
        h("span", { class: "pm-cp-rep-snippet" }, r.snippet || ""),
      ]));
    }

    setMax(false);
    resetPosSize(root);
    root.classList.add("open");
    anchorAbsolutely(root);
  }

  function close() {
    root.classList.remove("open");
    setMax(false);
    onClose?.();
  }

  fontSmaller.addEventListener("click", () => nudgeFont([root], -FONT_STEP));
  fontLarger .addEventListener("click", () => nudgeFont([root],  FONT_STEP));
  maxBtn  .addEventListener("click", () => setMax(!maximized));
  closeBtn.addEventListener("click", close);
  applyFontScale([root]);
  makeDraggable(root, head);

  return { root, open, close };
}
