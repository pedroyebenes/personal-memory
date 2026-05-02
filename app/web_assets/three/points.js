import * as THREE from "three";
import { clusterColor } from "./palette.js";

const HIGHLIGHT = new THREE.Color(0xffe36e);
const DIM       = new THREE.Color(0x25263a);

export function createPointCloud({ scene, points, vizData }) {
  const positions = new Float32Array(points.length * 3);
  const colors    = new Float32Array(points.length * 3);

  points.forEach((p, i) => {
    positions[i * 3] = p.x;
    positions[i * 3 + 1] = p.y;
    positions[i * 3 + 2] = p.z;
  });

  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geo.setAttribute("color",    new THREE.BufferAttribute(colors, 3));

  const mat = new THREE.PointsMaterial({
    size: 0.045,
    vertexColors: true,
    sizeAttenuation: true,
    transparent: true,
    opacity: 0.9,
  });
  const mesh = new THREE.Points(geo, mat);
  scene.add(mesh);

  function applyStyling({ activeClusterId, searchMatches, filteredOut }) {
    const colorAttr = geo.getAttribute("color");
    const col = new THREE.Color();
    for (let i = 0; i < points.length; i++) {
      const p = points[i];
      if (filteredOut && filteredOut.has(i)) {
        col.copy(DIM);
      } else if (searchMatches && searchMatches.has(i)) {
        col.copy(HIGHLIGHT);
      } else {
        col.set(clusterColor(p.cluster_id, vizData));
        if (activeClusterId !== null && activeClusterId !== undefined && p.cluster_id !== activeClusterId) {
          col.lerp(DIM, 0.78);
        }
      }
      colorAttr.setXYZ(i, col.r, col.g, col.b);
    }
    colorAttr.needsUpdate = true;
  }

  function setSize(value) {
    mat.size = value;
  }

  function dispose() {
    scene.remove(mesh);
    geo.dispose();
    mat.dispose();
  }

  return { mesh, applyStyling, setSize, dispose };
}
