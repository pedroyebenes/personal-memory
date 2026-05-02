import { h, mount, clear } from "../lib/h.js";
import { getConceptGraph, getConcept } from "../lib/api.js";

const PALETTE = [
  "#e05c7a", "#4fc3a1", "#f6a623", "#7b9fd4", "#c47bc1",
  "#80c770", "#f0886a", "#5dbcd2", "#d4af37", "#9b8eb8",
];

export const graphView = {
  mount(target, { store }) {
    const limitInput = h("input", { type: "number", value: "200", min: "20", max: "500", step: "10" });
    const minCoocInput = h("input", { type: "number", value: "2", min: "1", max: "20" });
    const reloadBtn = h("button", { class: "pm-primary", type: "button" }, "Reload");
    const search = h("input", { type: "search", placeholder: "Highlight concept" });
    const status = h("div", { class: "pm-empty" }, "Loading…");

    const rail = h("aside", { class: "pm-workbench-rail" }, [
      h("div", { class: "pm-section" }, [
        h("div", { class: "pm-section-title" }, "Concept network"),
        h("label", { class: "pm-field" }, [h("span", null, "Top concepts"), limitInput]),
        h("label", { class: "pm-field" }, [h("span", null, "Min co-occurrence"), minCoocInput]),
        reloadBtn,
        search,
        status,
      ]),
      h("div", { class: "pm-section", id: "pm-graph-detail" }),
    ]);

    const canvas = h("canvas", { class: "pm-graph-canvas" });
    Object.assign(canvas.style, { width: "100%", height: "100%", display: "block", cursor: "grab" });
    const main = h("section", {
      class: "pm-workbench-main",
      style: { padding: "0", position: "relative", overflow: "hidden" },
    }, [canvas]);

    target.appendChild(h("div", { class: "pm-workbench" }, [rail, main]));

    const detailHost = rail.querySelector("#pm-graph-detail");

    let nodes = [];      // [{id, name, type, mentions, x, y, vx, vy, color}]
    let edges = [];      // [{a, b, weight}]
    let nodeById = new Map();
    let selectedId = null;
    let hoverId = null;
    let highlightedIds = new Set();
    let rafId = 0;
    let zoom = 1, panX = 0, panY = 0;
    let dragging = null; // node being dragged
    let panning = false;
    let mouse = { x: 0, y: 0 };

    function colorForType(type) {
      let h = 0;
      const s = type || "concept";
      for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
      return PALETTE[h % PALETTE.length];
    }

    async function reload() {
      reloadBtn.disabled = true;
      mount(status, "Loading…");
      try {
        const payload = await getConceptGraph({
          limit: Number(limitInput.value) || 200,
          minCooccurrence: Number(minCoocInput.value) || 2,
          edgeLimit: 1500,
        });
        nodes = (payload.nodes || []).map((n, i) => ({
          id: n.id,
          name: n.canonical_name,
          type: n.entity_type,
          mentions: n.mention_count,
          x: Math.cos((i / Math.max(1, payload.nodes.length)) * Math.PI * 2) * 200,
          y: Math.sin((i / Math.max(1, payload.nodes.length)) * Math.PI * 2) * 200,
          vx: 0, vy: 0,
          color: colorForType(n.entity_type),
        }));
        nodeById = new Map(nodes.map((n) => [n.id, n]));
        edges = (payload.edges || []).filter((e) => nodeById.has(e.a) && nodeById.has(e.b));
        mount(status, h("span", null, `${nodes.length} concepts · ${edges.length} edges`));
        if (selectedId && nodeById.has(selectedId)) loadDetail(selectedId);
      } catch (err) {
        mount(status, h("span", { class: "pm-error" }, err.message));
      } finally {
        reloadBtn.disabled = false;
      }
    }

    reloadBtn.addEventListener("click", reload);

    search.addEventListener("input", () => {
      const q = search.value.trim().toLowerCase();
      highlightedIds = new Set();
      if (q.length >= 2) {
        for (const n of nodes) {
          if (n.name.toLowerCase().includes(q)) highlightedIds.add(n.id);
        }
      }
    });

    // ── Force layout (one tick per frame) ─────────────
    const REPULSION = 8000;
    const SPRING = 0.0012;
    const SPRING_LEN = 60;
    const CENTER_PULL = 0.0009;
    const DAMP = 0.86;

    function tick() {
      // Apply repulsion (pairwise)
      for (let i = 0; i < nodes.length; i++) {
        const ni = nodes[i];
        for (let j = i + 1; j < nodes.length; j++) {
          const nj = nodes[j];
          const dx = ni.x - nj.x;
          const dy = ni.y - nj.y;
          const d2 = dx * dx + dy * dy + 0.01;
          const f = REPULSION / d2;
          const d = Math.sqrt(d2);
          const fx = (dx / d) * f;
          const fy = (dy / d) * f;
          ni.vx += fx; ni.vy += fy;
          nj.vx -= fx; nj.vy -= fy;
        }
      }
      // Spring (edges)
      for (const e of edges) {
        const a = nodeById.get(e.a);
        const b = nodeById.get(e.b);
        if (!a || !b) continue;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const d = Math.sqrt(dx * dx + dy * dy + 0.001);
        const target = SPRING_LEN / Math.log2(2 + e.weight);
        const f = SPRING * (d - target) * Math.log2(2 + e.weight);
        const fx = (dx / d) * f;
        const fy = (dy / d) * f;
        a.vx += fx; a.vy += fy;
        b.vx -= fx; b.vy -= fy;
      }
      // Center pull
      for (const n of nodes) {
        n.vx -= n.x * CENTER_PULL;
        n.vy -= n.y * CENTER_PULL;
      }
      // Integrate
      for (const n of nodes) {
        if (dragging === n) { n.vx = 0; n.vy = 0; continue; }
        n.vx *= DAMP;
        n.vy *= DAMP;
        n.x += n.vx;
        n.y += n.vy;
      }
    }

    function radiusFor(n) {
      const r = 3 + Math.sqrt(n.mentions) * 0.8;
      return Math.min(28, Math.max(3, r));
    }

    function nodeAt(clientX, clientY) {
      const rect = canvas.getBoundingClientRect();
      const cx = (clientX - rect.left - rect.width / 2) / zoom - panX;
      const cy = (clientY - rect.top - rect.height / 2) / zoom - panY;
      for (let i = nodes.length - 1; i >= 0; i--) {
        const n = nodes[i];
        const dx = n.x - cx;
        const dy = n.y - cy;
        const r = radiusFor(n) + 2;
        if (dx * dx + dy * dy <= r * r) return n;
      }
      return null;
    }

    function draw() {
      const rect = canvas.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio, 2);
      if (canvas.width !== rect.width * dpr || canvas.height !== rect.height * dpr) {
        canvas.width = rect.width * dpr;
        canvas.height = rect.height * dpr;
      }
      const ctx = canvas.getContext("2d");
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.fillStyle = "#12121f";
      ctx.fillRect(0, 0, rect.width, rect.height);

      ctx.save();
      ctx.translate(rect.width / 2, rect.height / 2);
      ctx.scale(zoom, zoom);
      ctx.translate(panX, panY);

      // Edges
      for (const e of edges) {
        const a = nodeById.get(e.a);
        const b = nodeById.get(e.b);
        if (!a || !b) continue;
        const focus = selectedId != null && (a.id === selectedId || b.id === selectedId);
        const dim = highlightedIds.size > 0 && !highlightedIds.has(a.id) && !highlightedIds.has(b.id);
        ctx.strokeStyle = focus ? "rgba(158, 207, 184, 0.85)" : (dim ? "rgba(255,255,255,0.04)" : "rgba(255,255,255,0.10)");
        ctx.lineWidth = focus ? 1.5 : Math.min(2.5, 0.4 + Math.log2(e.weight) * 0.4);
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
      }

      // Nodes
      for (const n of nodes) {
        const r = radiusFor(n);
        const dim = highlightedIds.size > 0 && !highlightedIds.has(n.id);
        const focus = n.id === selectedId || n.id === hoverId;
        ctx.beginPath();
        ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
        ctx.fillStyle = focus ? "#9ecfb8" : (dim ? "rgba(85, 85, 106, 0.35)" : n.color);
        ctx.fill();
        if (focus) {
          ctx.strokeStyle = "rgba(158, 207, 184, 0.6)";
          ctx.lineWidth = 2;
          ctx.stroke();
        }
        // Always-on labels for top mentions or focused
        if (n.id === selectedId || n.id === hoverId || highlightedIds.has(n.id) || r >= 12) {
          ctx.fillStyle = "rgba(232, 232, 244, 0.92)";
          ctx.font = `${Math.min(14, 9 + r * 0.3)}px Georgia, serif`;
          ctx.textAlign = "center";
          ctx.textBaseline = "top";
          ctx.fillText(n.name, n.x, n.y + r + 3);
        }
      }
      ctx.restore();
    }

    function frame() {
      tick();
      draw();
      rafId = requestAnimationFrame(frame);
    }

    // ── Pointer interactions ────────────────────────
    canvas.addEventListener("mousedown", (e) => {
      const n = nodeAt(e.clientX, e.clientY);
      if (n) {
        dragging = n;
        canvas.style.cursor = "grabbing";
      } else {
        panning = true;
        canvas.style.cursor = "grabbing";
      }
      mouse = { x: e.clientX, y: e.clientY };
    });
    canvas.addEventListener("mousemove", (e) => {
      if (dragging) {
        const dx = (e.clientX - mouse.x) / zoom;
        const dy = (e.clientY - mouse.y) / zoom;
        dragging.x += dx;
        dragging.y += dy;
      } else if (panning) {
        panX += (e.clientX - mouse.x) / zoom;
        panY += (e.clientY - mouse.y) / zoom;
      } else {
        const n = nodeAt(e.clientX, e.clientY);
        hoverId = n?.id ?? null;
        canvas.style.cursor = n ? "pointer" : "grab";
      }
      mouse = { x: e.clientX, y: e.clientY };
    });
    canvas.addEventListener("mouseup", () => {
      dragging = null;
      panning = false;
      canvas.style.cursor = "grab";
    });
    canvas.addEventListener("mouseleave", () => {
      dragging = null;
      panning = false;
      hoverId = null;
    });
    canvas.addEventListener("click", (e) => {
      const n = nodeAt(e.clientX, e.clientY);
      if (n) selectNode(n.id);
    });
    canvas.addEventListener("wheel", (e) => {
      e.preventDefault();
      const factor = Math.exp(-e.deltaY * 0.001);
      zoom = Math.max(0.2, Math.min(4, zoom * factor));
    }, { passive: false });

    function selectNode(id) {
      selectedId = id;
      store.set({ selectedConceptId: id });
      loadDetail(id);
    }

    async function loadDetail(id) {
      mount(detailHost,
        h("div", { class: "pm-section-title" }, "Concept"),
        h("div", { class: "pm-empty" }, "Loading…"),
      );
      try {
        const d = await getConcept(id);
        const goSearch = h("button", { type: "button", onclick: () => {
          store.set({ query: d.canonical_name });
          location.hash = "#/search";
        } }, "Search");
        const docs = (d.related_documents || []).slice(0, 8);
        const reps = (d.top_chunks || []).slice(0, 3);
        clear(detailHost);
        detailHost.append(
          h("div", { class: "pm-section-title" }, "Concept"),
          h("h2", null, d.canonical_name),
          h("div", { class: "pm-evidence-meta" }, [
            h("span", null, `type: ${d.entity_type || "concept"}`),
            h("span", { style: { color: "var(--pm-fg-faint)" } }, "·"),
            h("span", null, `mentions: ${d.mention_count || 0}`),
          ]),
          h("div", { class: "pm-cp-section" }, [
            h("div", { class: "pm-cp-section-label" }, "Top documents"),
            ...docs.map((dx) =>
              h("div", { class: "pm-cp-doc-title" }, `${dx.document_title} (${dx.mention_count})`),
            ),
            !docs.length && h("div", { class: "pm-empty" }, "No documents."),
          ]),
          h("div", { class: "pm-cp-section" }, [
            h("div", { class: "pm-cp-section-label" }, "Excerpts"),
            ...reps.map((c) => h("div", { class: "pm-evidence-snippet" },
              (c.chunk_snippet || "").slice(0, 220) + (c.chunk_snippet?.length > 220 ? "…" : ""),
            )),
          ]),
          h("div", { class: "pm-evidence-actions" }, [goSearch]),
        );
      } catch (err) {
        mount(detailHost, h("div", { class: "pm-error" }, err.message));
      }
    }

    const offConcept = store.on("selectedConceptId", (id) => {
      if (id != null && id !== selectedId && nodeById.has(id)) {
        selectedId = id;
        loadDetail(id);
      }
    });

    // Boot
    reload().then(() => {
      // If a concept was preselected (e.g., from chat citation), auto-open.
      const sid = store.get("selectedConceptId");
      if (sid != null && nodeById.has(sid)) selectNode(sid);
    });
    rafId = requestAnimationFrame(frame);

    this._cleanup = () => {
      if (rafId) cancelAnimationFrame(rafId);
      offConcept();
    };
  },

  unmount() { this._cleanup?.(); },
};
