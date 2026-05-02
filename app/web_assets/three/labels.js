// HTML overlays for supercluster floating labels and per-point concept labels (LOD).

import * as THREE from "three";
import { superclusterColor, displayConceptTitle } from "./palette.js";

const tmpVec = new THREE.Vector3();
const tmpVec2 = new THREE.Vector3();

export function createSuperclusterLabels({ host, superclusters, vizData, onClick }) {
  host.innerHTML = "";
  const entries = [];
  for (const sc of superclusters || []) {
    if (!Array.isArray(sc.center) || sc.center.length < 3) continue;
    const el = document.createElement("div");
    el.className = "pm-supercluster-label" + (sc.is_noise ? " noise" : "");
    el.dataset.superclusterId = String(sc.id);
    const dot = document.createElement("span");
    dot.className = "pm-sc-dot";
    dot.style.background = superclusterColor(sc.id, vizData);
    el.appendChild(dot);
    el.appendChild(document.createTextNode(sc.name || `Group ${sc.id + 1}`));
    el.title = sc.name || `Group ${sc.id + 1}`;
    el.addEventListener("click", () => { if (!sc.is_noise) onClick?.(sc); });
    host.appendChild(el);
    entries.push({ el, world: new THREE.Vector3(sc.center[0], sc.center[1], sc.center[2]), data: sc });
  }
  let visible = true;

  function update(camera) {
    if (!entries.length) return;
    const w = host.clientWidth || window.innerWidth;
    const h = host.clientHeight || window.innerHeight;
    const margin = 8;
    for (const entry of entries) {
      if (!visible) { entry.el.style.display = "none"; continue; }
      tmpVec.copy(entry.world).project(camera);
      if (tmpVec.z < -1 || tmpVec.z > 1) { entry.el.style.display = "none"; continue; }
      const x = (tmpVec.x * 0.5 + 0.5) * w;
      const y = (-tmpVec.y * 0.5 + 0.5) * h;
      if (x < -margin || x > w + margin || y < -margin || y > h + margin) {
        entry.el.style.display = "none";
        continue;
      }
      entry.el.style.display = "";
      entry.el.style.left = `${x}px`;
      entry.el.style.top = `${y}px`;
    }
  }

  function setVisible(v) { visible = !!v; }
  function dispose() { host.innerHTML = ""; entries.length = 0; }

  return { update, setVisible, dispose };
}

// Per-point concept labels. Only points within `nearDistance` of the camera get
// a label, capped at `maxLabels`. Reuses a pool of HTML elements for perf.
export function createPointLabels({ host, points, maxLabels = 24, nearDistance = 1.6 }) {
  const pool = [];
  for (let i = 0; i < maxLabels; i++) {
    const el = document.createElement("div");
    el.className = "pm-point-label";
    el.style.display = "none";
    host.appendChild(el);
    pool.push(el);
  }
  let active = true;

  // Cache labels per index to avoid recomputing displayConceptTitle.
  const labelCache = new Map();
  function labelFor(i) {
    if (!labelCache.has(i)) labelCache.set(i, displayConceptTitle(points[i]));
    return labelCache.get(i);
  }

  function update(camera, filteredOut, activeClusterId) {
    if (!active) {
      for (const el of pool) el.style.display = "none";
      return;
    }
    const w = host.clientWidth  || window.innerWidth;
    const h = host.clientHeight || window.innerHeight;
    const camPos = camera.position;

    // Pick the closest N points that pass filter / cluster.
    const candidates = [];
    for (let i = 0; i < points.length; i++) {
      if (filteredOut && filteredOut.has(i)) continue;
      if (activeClusterId != null && points[i].cluster_id !== activeClusterId) continue;
      const dx = points[i].x - camPos.x;
      const dy = points[i].y - camPos.y;
      const dz = points[i].z - camPos.z;
      const d2 = dx * dx + dy * dy + dz * dz;
      if (d2 > nearDistance * nearDistance) continue;
      candidates.push([d2, i]);
    }
    candidates.sort((a, b) => a[0] - b[0]);
    const slice = candidates.slice(0, maxLabels);

    for (let k = 0; k < pool.length; k++) {
      const el = pool[k];
      const c = slice[k];
      if (!c) { el.style.display = "none"; continue; }
      const i = c[1];
      const p = points[i];
      tmpVec2.set(p.x, p.y, p.z).project(camera);
      if (tmpVec2.z < -1 || tmpVec2.z > 1) { el.style.display = "none"; continue; }
      const x = (tmpVec2.x * 0.5 + 0.5) * w;
      const y = (-tmpVec2.y * 0.5 + 0.5) * h;
      el.style.display = "";
      el.style.left = `${x}px`;
      el.style.top = `${y - 6}px`;
      el.textContent = labelFor(i);
    }
  }

  function setActive(v) { active = !!v; }
  function dispose() { host.innerHTML = ""; pool.length = 0; labelCache.clear(); }

  return { update, setActive, dispose };
}
