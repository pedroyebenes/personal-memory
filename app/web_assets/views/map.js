import * as THREE from "three";

import { h, clear } from "../lib/h.js";
import { getViz } from "../lib/api.js";
import { createScene } from "../three/scene.js";
import { createPointCloud } from "../three/points.js";
import { createEdges } from "../three/edges.js";
import { createSuperclusterLabels, createPointLabels } from "../three/labels.js";
import { clusterColor, superclusterColor, clusterSummary, displayConceptTitle } from "../three/palette.js";
import { buildNotePopover, buildClusterPopover } from "../components/popovers.js";

let cssLoaded = false;
function ensureMapCss() {
  if (cssLoaded) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = "/static/styles/map.css";
  document.head.appendChild(link);
  cssLoaded = true;
}

export const mapView = {
  mount(target, { store }) {
    ensureMapCss();

    // ── DOM scaffold ────────────────────────────────
    const canvasContainer = h("div", { class: "pm-map-canvas" });
    const tooltip = h("div", { class: "pm-tooltip" }, [
      h("div", { class: "pm-tt-concept" }),
      h("div", { class: "pm-tt-doc" }),
      h("div", { class: "pm-tt-text" }),
    ]);
    const superclusterHost = h("div", { class: "pm-supercluster-host", "aria-hidden": "true" });
    const pointLabelHost = h("div", { class: "pm-point-label-host", "aria-hidden": "true" });

    const sidebar = h("aside", { class: "pm-map-sidebar" });
    const meta = h("div", { class: "pm-map-meta" }, [
      h("div", { class: "pm-map-meta-row" }, "Embedding Space"),
      h("div", { class: "pm-map-meta-row", id: "pm-meta-chunks" }),
      h("div", { class: "pm-map-meta-row", id: "pm-meta-clusters" }),
      h("div", { class: "pm-map-meta-row", id: "pm-meta-supers" }),
      h("div", { class: "pm-map-meta-row", id: "pm-meta-projection" }),
    ]);

    const searchInput = h("input", { type: "search", placeholder: "Search concepts, docs, snippets" });
    const searchMeta = h("div", { class: "pm-map-search-meta" }, "Search highlights matching points.");

    const autoRotate = h("input", { type: "checkbox", checked: true });
    const showLabels = h("input", { type: "checkbox", checked: true });
    const showSupers = h("input", { type: "checkbox", checked: true });
    const pointSize  = h("input", { type: "range", min: "1", max: "16", value: "5", step: "1" });

    const edgeButtons = ["fullD", "3d", "off"].map((mode) =>
      h("button", { type: "button", class: "pm-map-edge-btn", "data-mode": mode },
        mode === "fullD" ? "Full-D" : mode === "3d" ? "3D" : "Off"),
    );

    const controls = h("div", { class: "pm-map-controls" }, [
      h("div", { class: "pm-section", style: { gap: "var(--pm-sp-1)" } }, [searchInput, searchMeta]),
      h("label", { class: "pm-toggle" }, [autoRotate, h("span", null, "Auto-rotate")]),
      h("label", { class: "pm-toggle" }, [showLabels, h("span", null, "Concept labels")]),
      h("label", { class: "pm-toggle" }, [showSupers, h("span", null, "Supercluster labels")]),
      h("label", { class: "pm-field" }, [h("span", null, "Point size"), pointSize]),
      h("div", { class: "pm-section", style: { gap: "var(--pm-sp-1)" } }, [
        h("span", { class: "pm-section-title" }, "Edges"),
        h("div", { class: "pm-map-edge-row" }, edgeButtons),
      ]),
    ]);

    const legend = h("div", { class: "pm-map-legend" }, [
      h("div", { class: "pm-legend-heading" }, "Clusters"),
      h("div", { class: "pm-legend-list", id: "pm-legend-list" }),
    ]);

    sidebar.append(meta, controls, legend);

    const notePopover = buildNotePopover();
    let clusterPopoverApi = null; // built after vizData arrives

    const overlay = h("div", { class: "pm-overlay" }, [
      h("div", { class: "pm-spinner" }),
      h("span", null, "Computing clusters & projection…"),
    ]);

    const root = h("div", { class: "pm-map" }, [
      canvasContainer, superclusterHost, pointLabelHost,
      sidebar, tooltip, notePopover.root, overlay,
    ]);
    target.appendChild(root);

    // ── State ───────────────────────────────────────
    let vizData = null;
    let activeClusterId = null;
    let searchMatches = new Set();
    let filteredOut = new Set();
    let edgeMode = "fullD";
    let scene, camera, renderer, controls3d, sceneApi;
    let pointCloud, edges, superLabels, pointLabels;
    let rafId = 0;
    let hoverTimer = null;
    let onResizeListener = null;

    // ── Boot ─────────────────────────────────────────
    (async () => {
      try {
        const data = await getViz();
        if (!data || !data.points) {
          showError("No visualization data available.");
          return;
        }
        vizData = data;

        renderMeta();
        sceneApi = createScene(canvasContainer);
        scene = sceneApi.scene; camera = sceneApi.camera;
        renderer = sceneApi.renderer; controls3d = sceneApi.controls;

        pointCloud = createPointCloud({ scene, points: data.points, vizData });
        edges = createEdges({ scene, points: data.points, edges: data.edges || [], vizData });
        edges.setMode(edgeMode);
        superLabels = createSuperclusterLabels({
          host: superclusterHost,
          superclusters: data.superclusters || [],
          vizData,
          onClick: focusSupercluster,
        });
        pointLabels = createPointLabels({
          host: pointLabelHost,
          points: data.points,
          maxLabels: 28,
          nearDistance: 1.6,
        });

        clusterPopoverApi = buildClusterPopover({
          onSelectPoint: ({ kind, index, point }) => {
            if (kind === "focus" && index != null) focusPoint(index);
            if (kind === "open"  && point) notePopover.open(point);
          },
          onClose: () => {
            activeClusterId = null;
            updateLegendState();
            applyStyling();
          },
        });
        target.appendChild(clusterPopoverApi.root);

        buildLegend();
        updateLegendState();
        applyStyling();
        wireInteractions();
        wireUiControls();

        animate();
        overlay.remove();
      } catch (err) {
        showError(err.message || "Failed to load visualization data.");
      }
    })();

    function renderMeta() {
      const data = vizData;
      meta.querySelector("#pm-meta-chunks").innerHTML =
        `<strong>${data.points.length.toLocaleString()}</strong> chunks`;
      meta.querySelector("#pm-meta-clusters").innerHTML =
        `<strong>${data.n_clusters}</strong> clusters`;
      const nSuper = (data.superclusters || []).filter((s) => !s.is_noise).length;
      meta.querySelector("#pm-meta-supers").innerHTML = nSuper
        ? `<strong>${nSuper}</strong> supercluster${nSuper === 1 ? "" : "s"}` : "";
      const proj = meta.querySelector("#pm-meta-projection");
      if (data.projection === "umap") {
        proj.innerHTML = "Projection: <strong>UMAP</strong> (cosine)";
      } else if (data.projection === "pca" && data.variance_explained?.length) {
        const pct = data.variance_explained.slice(0, 3).map((v) => (v * 100).toFixed(1) + "%").join(" + ");
        proj.innerHTML = `Projection: PCA · variance ${pct}`;
      } else {
        proj.innerHTML = "";
      }
    }

    // ── Legend ──────────────────────────────────────
    function buildLegend() {
      const list = legend.querySelector("#pm-legend-list");
      clear(list);
      const clusters = vizData?.clusters || [];
      const superclusters = vizData?.superclusters || [];

      function makeItem(summary) {
        const item = h("button", {
          type: "button",
          class: "pm-legend-item" + (summary.is_noise ? " noise" : ""),
          dataset: { clusterId: String(summary.id) },
          onclick: () => {
            const wasActive = activeClusterId === summary.id;
            activeClusterId = wasActive ? null : summary.id;
            updateLegendState();
            applyStyling();
            if (activeClusterId !== null) {
              focusCluster(activeClusterId);
              clusterPopoverApi?.open(clusterSummary(activeClusterId, vizData), vizData);
            } else {
              clusterPopoverApi?.close();
            }
          },
        }, [
          h("div", { class: "pm-legend-swatch", style: { background: clusterColor(summary.id, vizData) } }),
          h("span", { class: "pm-legend-text" }, [
            h("span", { class: "pm-legend-name" }, summary.name || `Cluster ${summary.id + 1}`),
            h("span", { class: "pm-legend-count" }, `${summary.size.toLocaleString()} chunk${summary.size === 1 ? "" : "s"}`),
          ]),
        ]);
        return item;
      }

      if (superclusters.length) {
        const byCluster = new Map(clusters.map((c) => [c.id, c]));
        const ordered = superclusters.slice().sort((a, b) => {
          if (!!a.is_noise !== !!b.is_noise) return a.is_noise ? 1 : -1;
          return b.size - a.size;
        });
        for (const sc of ordered) {
          const group = h("div", { class: "pm-legend-supergroup" + (sc.is_noise ? " noise" : "") }, [
            h("div", { class: "pm-legend-supergroup-head" }, [
              h("span", { class: "pm-sg-swatch", style: { background: superclusterColor(sc.id, vizData) } }),
              h("span", { class: "pm-legend-name" }, sc.name || `Group ${sc.id + 1}`),
            ]),
          ]);
          const members = (sc.cluster_ids || [])
            .map((cid) => byCluster.get(cid))
            .filter(Boolean)
            .sort((a, b) => {
              if (!!a.is_noise !== !!b.is_noise) return a.is_noise ? 1 : -1;
              return b.size - a.size;
            });
          for (const c of members) group.appendChild(makeItem(c));
          list.appendChild(group);
        }
        const assigned = new Set();
        for (const sc of superclusters) for (const cid of sc.cluster_ids || []) assigned.add(cid);
        const orphans = clusters.filter((c) => !assigned.has(c.id));
        if (orphans.length) {
          const group = h("div", { class: "pm-legend-supergroup" });
          for (const c of orphans) group.appendChild(makeItem(c));
          list.appendChild(group);
        }
        return;
      }
      const order = clusters.slice().sort((a, b) => b.size - a.size);
      for (const c of order) list.appendChild(makeItem(c));
    }

    function updateLegendState() {
      for (const item of legend.querySelectorAll(".pm-legend-item")) {
        const id = Number(item.dataset.clusterId);
        item.classList.toggle("active", activeClusterId === id);
        item.classList.toggle("dimmed", activeClusterId !== null && activeClusterId !== id);
      }
    }

    // ── Filter integration ──────────────────────────
    function recomputeFilteredOut() {
      const f = store.get("filters") || {};
      filteredOut = new Set();
      const tags = (f.tags || []).map((t) => t.toLowerCase());
      const aliases = (f.aliases || []).map((t) => t.toLowerCase());
      const path = (f.path_prefix || "").trim();
      if (!tags.length && !aliases.length && !path) return;
      vizData?.points?.forEach((p, i) => {
        const ptags = (p.tags || []).map((t) => t.toLowerCase());
        const palias = (p.aliases || []).map((t) => t.toLowerCase());
        if (tags.length && !tags.every((t) => ptags.includes(t))) { filteredOut.add(i); return; }
        if (aliases.length && !aliases.every((a) => palias.includes(a))) { filteredOut.add(i); return; }
        if (path && !(p.source_path || "").startsWith(path)) { filteredOut.add(i); return; }
      });
    }
    const offFilters = store.on("filters", () => {
      recomputeFilteredOut();
      applyStyling();
    });
    recomputeFilteredOut();

    // ── Camera focus helpers ────────────────────────
    function focusPoint(i) {
      const p = vizData.points[i];
      if (!p) return;
      const target = new THREE.Vector3(p.x, p.y, p.z);
      const dir = camera.position.clone().sub(controls3d.target).normalize();
      controls3d.target.copy(target);
      camera.position.copy(target).add(dir.multiplyScalar(1.25));
      controls3d.autoRotate = false;
      autoRotate.checked = false;
      controls3d.update();
    }

    function focusCluster(id) {
      const points = vizData.points.filter((p) => p.cluster_id === id);
      if (!points.length) return;
      const center = points.reduce((acc, p) => acc.add(new THREE.Vector3(p.x, p.y, p.z)),
        new THREE.Vector3()).multiplyScalar(1 / points.length);
      const radius = Math.max(0.7,
        ...points.map((p) => center.distanceTo(new THREE.Vector3(p.x, p.y, p.z))));
      const dir = camera.position.clone().sub(controls3d.target).normalize();
      controls3d.target.copy(center);
      camera.position.copy(center).add(dir.multiplyScalar(Math.min(4.2, radius * 2.6 + 0.9)));
      controls3d.autoRotate = false;
      autoRotate.checked = false;
      controls3d.update();
    }

    function focusSupercluster(sc) {
      if (!sc?.cluster_ids?.length) return;
      const set = new Set(sc.cluster_ids);
      const members = vizData.points.filter((p) => set.has(p.cluster_id));
      if (!members.length) return;
      const center = members.reduce((acc, p) => acc.add(new THREE.Vector3(p.x, p.y, p.z)),
        new THREE.Vector3()).multiplyScalar(1 / members.length);
      const radius = Math.max(0.9,
        ...members.map((p) => center.distanceTo(new THREE.Vector3(p.x, p.y, p.z))));
      const dir = camera.position.clone().sub(controls3d.target).normalize();
      controls3d.target.copy(center);
      camera.position.copy(center).add(dir.multiplyScalar(Math.min(5.5, radius * 2.2 + 1.2)));
      controls3d.autoRotate = false;
      autoRotate.checked = false;
      controls3d.update();
    }

    // ── Hover + dblclick ───────────────────────────
    function wireInteractions() {
      const raycaster = new THREE.Raycaster();
      raycaster.params.Points.threshold = 0.04;
      const mouse = new THREE.Vector2(-9, -9);

      function pick(clientX, clientY) {
        const rect = renderer.domElement.getBoundingClientRect();
        mouse.x =  ((clientX - rect.left) / rect.width)  * 2 - 1;
        mouse.y = -((clientY - rect.top)  / rect.height) * 2 + 1;
        raycaster.setFromCamera(mouse, camera);
        const hits = raycaster.intersectObject(pointCloud.mesh);
        const hit = hits.find((it) => pointPasses(it.index));
        return hit ? vizData.points[hit.index] : null;
      }

      renderer.domElement.addEventListener("dblclick", (e) => {
        e.preventDefault();
        const p = pick(e.clientX, e.clientY);
        if (p) notePopover.open(p);
      });

      renderer.domElement.addEventListener("mousemove", (e) => {
        if (notePopover.isOpen()) { tooltip.style.display = "none"; return; }
        if (hoverTimer) clearTimeout(hoverTimer);
        hoverTimer = setTimeout(() => {
          hoverTimer = null;
          if (notePopover.isOpen()) return;
          const p = pick(e.clientX, e.clientY);
          if (p) {
            tooltip.querySelector(".pm-tt-concept").textContent = displayConceptTitle(p);
            tooltip.querySelector(".pm-tt-doc").textContent = p.document_title || "";
            tooltip.querySelector(".pm-tt-text").textContent = p.snippet || "";
            tooltip.style.left = `${Math.min(e.clientX + 16, window.innerWidth  - 320)}px`;
            tooltip.style.top  = `${Math.min(e.clientY + 16, window.innerHeight - 180)}px`;
            tooltip.style.display = "block";
          } else {
            tooltip.style.display = "none";
          }
        }, 35);
      });

      renderer.domElement.addEventListener("mouseleave", () => { tooltip.style.display = "none"; });

      window.addEventListener("keydown", escHandler);
    }

    function escHandler(e) {
      if (e.key !== "Escape") return;
      if (notePopover.isOpen()) {
        e.preventDefault();
        notePopover.close();
      } else if (activeClusterId !== null) {
        e.preventDefault();
        clusterPopoverApi?.close();
        activeClusterId = null;
        updateLegendState();
        applyStyling();
      }
    }

    // ── UI controls wiring ─────────────────────────
    function wireUiControls() {
      searchInput.addEventListener("input", (e) => {
        const q = e.target.value.trim().toLowerCase();
        searchMatches = new Set();
        if (q.length >= 2) {
          vizData.points.forEach((p, i) => {
            const text = [
              p.top_concept?.canonical_name, p.document_title, p.snippet,
            ].filter(Boolean).join(" ").toLowerCase();
            if (text.includes(q)) searchMatches.add(i);
          });
        }
        searchMeta.textContent = q.length < 2
          ? "Search highlights matching points."
          : `${searchMatches.size.toLocaleString()} matching chunk${searchMatches.size === 1 ? "" : "s"}`;
        applyStyling();
        if (searchMatches.size) focusPoint([...searchMatches][0]);
      });
      searchInput.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
          searchInput.value = "";
          searchMatches = new Set();
          searchMeta.textContent = "Search highlights matching points.";
          applyStyling();
        }
      });

      autoRotate.addEventListener("change", () => { controls3d.autoRotate = autoRotate.checked; });
      showLabels.addEventListener("change", () => { pointLabels.setActive(showLabels.checked); });
      showSupers.addEventListener("change", () => { superLabels.setVisible(showSupers.checked); });
      pointSize.addEventListener("input", () => { pointCloud.setSize(parseFloat(pointSize.value) * 0.009); });

      for (const btn of edgeButtons) {
        btn.addEventListener("click", () => setEdgeMode(btn.dataset.mode));
      }
      setEdgeMode("fullD"); // initial
    }

    function setEdgeMode(mode) {
      edgeMode = mode;
      edges?.setMode(mode);
      for (const btn of edgeButtons) {
        btn.setAttribute("aria-pressed", btn.dataset.mode === mode ? "true" : "false");
      }
    }

    // ── Styling + render loop ──────────────────────
    function pointPasses(i) {
      if (filteredOut.has(i)) return false;
      if (activeClusterId == null) return true;
      return vizData.points[i].cluster_id === activeClusterId;
    }
    function applyStyling() {
      pointCloud?.applyStyling({ activeClusterId, searchMatches, filteredOut });
    }

    function animate() {
      rafId = requestAnimationFrame(animate);
      controls3d.update();
      renderer.render(scene, camera);
      superLabels?.update(camera);
      pointLabels?.update(camera, filteredOut, activeClusterId);
    }

    function showError(message) {
      clear(overlay);
      overlay.appendChild(h("div", { class: "pm-error" }, message));
    }

    // ── Cleanup ────────────────────────────────────
    this._cleanup = () => {
      if (rafId) cancelAnimationFrame(rafId);
      if (hoverTimer) clearTimeout(hoverTimer);
      window.removeEventListener("keydown", escHandler);
      offFilters();
      pointCloud?.dispose();
      edges?.dispose();
      superLabels?.dispose();
      pointLabels?.dispose();
      sceneApi?.dispose();
    };
  },

  unmount() { this._cleanup?.(); },
};
