// Three-way theme: "dark" | "light" | "manuscript".
// "manuscript" is a single-mode decorative theme (no light/dark variant).
// The light/dark toggle ignores manuscript and cycles only between dark/light.
// The manuscript toggle saves/restores the previous dark/light theme.

import { loadPref, savePref } from "./storage.js";

const KEY        = "theme";
const PRE_MS_KEY = "theme-before-manuscript";
const VALID      = new Set(["dark", "light", "manuscript"]);

export function loadTheme() {
  const v = loadPref(KEY, "dark");
  return VALID.has(v) ? v : "dark";
}

export function applyTheme(theme) {
  const t = VALID.has(theme) ? theme : "dark";
  document.documentElement.dataset.theme = t;
  document.body.dataset.theme = t;
  savePref(KEY, t);
  return t;
}

// Cycles only between "dark" and "light". Exits manuscript if active.
export function toggleTheme() {
  const current = document.documentElement.dataset.theme || loadTheme();
  if (current === "manuscript") {
    const prev = loadPref(PRE_MS_KEY, "dark");
    return applyTheme(prev === "light" ? "dark" : "light");
  }
  return applyTheme(current === "light" ? "dark" : "light");
}

// Toggles the manuscript theme on/off, preserving dark/light state.
export function toggleManuscript() {
  const current = document.documentElement.dataset.theme || loadTheme();
  if (current === "manuscript") {
    const prev = loadPref(PRE_MS_KEY, "dark");
    return applyTheme(VALID.has(prev) && prev !== "manuscript" ? prev : "dark");
  }
  savePref(PRE_MS_KEY, current);
  return applyTheme("manuscript");
}
