// Typed localStorage helpers. All keys are namespaced under "pm-v2/" to avoid
// colliding with the legacy app.js keys (which use "personal-memory-*").

const NS = "pm-v2/";

function read(key, fallback) {
  try {
    const raw = localStorage.getItem(NS + key);
    if (raw == null) return fallback;
    return JSON.parse(raw);
  } catch {
    return fallback;
  }
}

function write(key, value) {
  try { localStorage.setItem(NS + key, JSON.stringify(value)); }
  catch { /* quota / disabled — no-op */ }
}

function remove(key) {
  try { localStorage.removeItem(NS + key); } catch { /* ignore */ }
}

// Recent queries — bounded ring of strings, most-recent-first.
const RECENTS_KEY = "recent-queries";
const RECENTS_MAX = 12;

export function loadRecents() {
  const v = read(RECENTS_KEY, []);
  return Array.isArray(v) ? v.filter((s) => typeof s === "string") : [];
}
export function pushRecent(query) {
  if (!query || !query.trim()) return loadRecents();
  const trimmed = query.trim();
  const next = [trimmed, ...loadRecents().filter((q) => q !== trimmed)].slice(0, RECENTS_MAX);
  write(RECENTS_KEY, next);
  return next;
}
export function clearRecents() { remove(RECENTS_KEY); }

// Saved searches — array of {name, query, filters}.
const SAVED_KEY = "saved-searches";
export function loadSaved() {
  const v = read(SAVED_KEY, []);
  return Array.isArray(v) ? v : [];
}
export function saveSaved(entry) {
  const list = loadSaved().filter((e) => e.name !== entry.name);
  list.unshift(entry);
  write(SAVED_KEY, list);
  return list;
}
export function deleteSaved(name) {
  const list = loadSaved().filter((e) => e.name !== name);
  write(SAVED_KEY, list);
  return list;
}

// Workspaces (chat history) — array of {id, query, response, mode, createdAt}.
const WORKSPACES_KEY = "workspaces";
const WORKSPACES_MAX = 24;
export function loadWorkspaces() {
  const v = read(WORKSPACES_KEY, []);
  return Array.isArray(v) ? v : [];
}
export function saveWorkspaces(list) {
  write(WORKSPACES_KEY, list.slice(0, WORKSPACES_MAX));
}

// Generic preferences — opaque object keyed by name.
export function loadPref(key, fallback) { return read("pref/" + key, fallback); }
export function savePref(key, value)    { write("pref/" + key, value); }
