// Hash-based router. Routes are flat: `#/<route>` (and ignore the rest).
// Each view exports `{ mount(target, ctx), unmount() }`. unmount is optional.

import { clear } from "../lib/h.js";

export function createRouter({ views, defaultRoute, target, store }) {
  let activeRoute = null;
  let activeView = null;

  function parseHash() {
    const raw = location.hash.slice(2); // strip "#/"
    const route = (raw.split("/")[0] || "").trim();
    return route in views ? route : defaultRoute;
  }

  function navigate() {
    const next = parseHash();
    if (next === activeRoute) return;
    if (activeView?.unmount) {
      try { activeView.unmount(); } catch (err) { console.error(err); }
    }
    clear(target);
    activeRoute = next;
    activeView = views[next];
    document.body.dataset.route = next;
    if (store) store.set({ route: next });
    activeView.mount(target, { store });
  }

  window.addEventListener("hashchange", navigate);

  // If no hash, set a default (avoids a flash of wrong route).
  if (!location.hash || !(parseHash() in views)) {
    location.replace(`#/${defaultRoute}`);
  }
  navigate();

  return {
    go(route) { location.hash = `#/${route}`; },
    current() { return activeRoute; },
  };
}
