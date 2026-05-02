import * as THREE from "three";
import { clusterColor } from "./palette.js";

// Mode is one of: 'fullD', '3d', 'off'.
// 'fullD' uses the server-supplied edges (NN in full-D cosine space).
// '3d' computes nearest neighbors in the projected 3D space (visually cleaner).
// 'off' hides edges.
export function createEdges({ scene, points, edges, vizData }) {
  let lines = null;

  function buildLineSegments(pairs) {
    const positions = new Float32Array(pairs.length * 6);
    const colors    = new Float32Array(pairs.length * 6);
    const colA = new THREE.Color();
    const colB = new THREE.Color();
    pairs.forEach(([i, j], e) => {
      const pi = points[i];
      const pj = points[j];
      if (!pi || !pj) return;
      positions[e * 6]     = pi.x; positions[e * 6 + 1] = pi.y; positions[e * 6 + 2] = pi.z;
      positions[e * 6 + 3] = pj.x; positions[e * 6 + 4] = pj.y; positions[e * 6 + 5] = pj.z;
      colA.set(clusterColor(pi.cluster_id, vizData));
      colB.set(clusterColor(pj.cluster_id, vizData));
      colors[e * 6]     = colA.r; colors[e * 6 + 1] = colA.g; colors[e * 6 + 2] = colA.b;
      colors[e * 6 + 3] = colB.r; colors[e * 6 + 4] = colB.g; colors[e * 6 + 5] = colB.b;
    });
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    geo.setAttribute("color",    new THREE.BufferAttribute(colors, 3));
    return new THREE.LineSegments(geo, new THREE.LineBasicMaterial({
      vertexColors: true, transparent: true, opacity: 0.18,
    }));
  }

  function clearLines() {
    if (!lines) return;
    scene.remove(lines);
    lines.geometry.dispose();
    lines.material.dispose();
    lines = null;
  }

  function setMode(mode) {
    clearLines();
    if (mode === "off") return;
    const pairs = mode === "3d" ? compute3dEdges(points, 3) : edges;
    if (!pairs?.length) return;
    lines = buildLineSegments(pairs);
    scene.add(lines);
  }

  function dispose() { clearLines(); }

  return { setMode, dispose };
}

// Brute-force k-NN in 3D. O(n²) but capped: cluster representatives only when
// n > 4000, otherwise full set. Each pair is added once via i < j.
function compute3dEdges(points, k = 3) {
  const n = points.length;
  if (n < 2) return [];
  const sample = n > 4000
    ? points.map((_, i) => i).filter((i) => i % Math.ceil(n / 4000) === 0)
    : points.map((_, i) => i);
  const seen = new Set();
  const pairs = [];
  for (const i of sample) {
    const pi = points[i];
    const dists = [];
    for (const j of sample) {
      if (i === j) continue;
      const pj = points[j];
      const dx = pi.x - pj.x, dy = pi.y - pj.y, dz = pi.z - pj.z;
      dists.push([dx * dx + dy * dy + dz * dz, j]);
    }
    dists.sort((a, b) => a[0] - b[0]);
    for (let m = 0; m < Math.min(k, dists.length); m++) {
      const [, j] = dists[m];
      const key = i < j ? `${i}-${j}` : `${j}-${i}`;
      if (seen.has(key)) continue;
      seen.add(key);
      pairs.push([i, j]);
    }
  }
  return pairs;
}
