// Light/dark theme. Persisted via storage.js. Default is dark (the original
// observatory aesthetic). The map view's WebGL scene reads its bg from CSS
// at mount time, so switching theme while the map is on screen is best
// followed by re-entering #/map; everything else is pure CSS and updates
// instantly.

import { loadPref, savePref } from "./storage.js";

const KEY = "theme";
const VALID = new Set(["dark", "light"]);

export function loadTheme() {
  const v = loadPref(KEY, "dark");
  return VALID.has(v) ? v : "dark";
}

export function applyTheme(theme) {
  const t = VALID.has(theme) ? theme : "dark";
  document.documentElement.dataset.theme = t;
  // Also reflect on <body> so existing `data-theme` selectors work either way.
  document.body.dataset.theme = t;
  savePref(KEY, t);
  return t;
}

export function toggleTheme() {
  const current = document.documentElement.dataset.theme || loadTheme();
  return applyTheme(current === "light" ? "dark" : "light");
}
