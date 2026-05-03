import { h } from "../lib/h.js";

export const NAV_ITEMS = [
  { route: "chat",   label: "Chat",   glyph: "◐" },
  { route: "search", label: "Search", glyph: "◷" },
  { route: "map",    label: "Map",    glyph: "⌖" },
  { route: "graph",  label: "Graph",  glyph: "✦" },
  { route: "docs",   label: "Docs",   glyph: "☰" },
];

export function buildNav({ store }) {
  const links = NAV_ITEMS.map((it) =>
    h("a", {
      class: "pm-nav-link",
      href: `#/${it.route}`,
      "data-route": it.route,
    }, [
      h("span", { class: "pm-nav-glyph", "aria-hidden": "true" }, it.glyph),
      h("span", { class: "pm-nav-label" }, it.label),
    ]),
  );

  const root = h("nav", { class: "pm-nav", role: "navigation", "aria-label": "Main views" }, [
    h("div", { class: "pm-brand" }, [
      h("span", { class: "pm-brand-mark", "aria-hidden": "true" }, "🧠"),
      h("span", null, "Personal Memory"),
    ]),
    ...links,
  ]);

  function syncActive(route) {
    for (const link of links) {
      if (link.dataset.route === route) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    }
  }

  if (store) {
    syncActive(store.get("route"));
    store.on("route", syncActive);
  }

  return root;
}
