// Header control: hide/show the left rail (workbench sidebar + map sidebar).

import { loadPref, savePref } from "../lib/storage.js";

const PREF_KEY = "railCollapsed";
const isMobileViewport = () => window.matchMedia("(max-width: 880px)").matches;

/** @param {HTMLElement} appEl */
export function buildRailToggle(appEl) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "pm-rail-toggle";

  let collapsed = !!loadPref(PREF_KEY, isMobileViewport());

  function applyDataset() {
    if (collapsed) appEl.dataset.railCollapsed = "true";
    else delete appEl.dataset.railCollapsed;
  }

  function syncButton() {
    applyDataset();
    btn.setAttribute("aria-pressed", collapsed ? "true" : "false");
    btn.setAttribute(
      "aria-label",
      collapsed ? "Show side panel" : "Hide side panel",
    );
    btn.title = collapsed ? "Show side panel" : "Hide side panel";
    btn.textContent = collapsed ? "»" : "«";
  }

  btn.addEventListener("click", () => {
    collapsed = !collapsed;
    savePref(PREF_KEY, collapsed);
    syncButton();
  });

  // Close rail overlay when tapping outside it on mobile
  document.addEventListener("click", (e) => {
    if (!collapsed && isMobileViewport() &&
        !e.target.closest(".pm-workbench-rail") &&
        !e.target.closest(".pm-rail-toggle")) {
      collapsed = true;
      savePref(PREF_KEY, collapsed);
      syncButton();
    }
  }, { capture: true });

  syncButton();
  return btn;
}
