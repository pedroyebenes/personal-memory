// Entry point for the v2 shell. Wires nav + status bar into the header,
// initializes the store, and starts the hash router with all view modules.

import { createStore } from "../lib/store.js";
import { applyTheme, loadTheme } from "../lib/theme.js";
import { buildNav } from "./nav.js";
import { buildStatusBar } from "./status-bar.js";
import { createRouter } from "./router.js";

import { chatView }   from "../views/chat.js";
import { searchView } from "../views/search.js";
import { mapView }    from "../views/map.js";
import { graphView }  from "../views/graph.js";
import { docsView }   from "../views/docs.js";

// The inline boot script in index.html already applied the theme; calling
// applyTheme() here keeps lib/storage.js as the single source of truth.
applyTheme(loadTheme());

const store = createStore({
  route: "chat",
  query: "",
  filters: { tags: [], aliases: [], path_prefix: null, date_from: null, date_to: null },
  selectedDocumentId: null,
  selectedConceptId: null,
  status: null,
  theme: loadTheme(),
});

const header = document.getElementById("pm-header");
const mountTarget = document.getElementById("view-mount");

header.appendChild(buildNav({ store }));

const statusBar = buildStatusBar({ store });
header.appendChild(statusBar.root);
statusBar.start();

createRouter({
  views: {
    chat:   chatView,
    search: searchView,
    map:    mapView,
    graph:  graphView,
    docs:   docsView,
  },
  defaultRoute: "chat",
  target: mountTarget,
  store,
});

// Expose for ad-hoc debugging in DevTools.
window.__pm = { store };
