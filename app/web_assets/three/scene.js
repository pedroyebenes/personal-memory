import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

function readThemeColor(name, fallback) {
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  if (!raw) return new THREE.Color(fallback);
  // THREE.Color.set accepts CSS color strings (#hex, rgb(...), named).
  try {
    return new THREE.Color(raw);
  } catch {
    return new THREE.Color(fallback);
  }
}

export function createScene(container) {
  const scene = new THREE.Scene();
  const bg = readThemeColor("--pm-bg-base", 0x12121f);
  scene.background = bg;
  scene.fog = new THREE.FogExp2(bg.getHex(), 0.05);

  const w = container.clientWidth || window.innerWidth;
  const h = container.clientHeight || window.innerHeight;

  const camera = new THREE.PerspectiveCamera(55, w / h, 0.01, 120);
  camera.position.set(0, 0, 3.8);

  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(w, h);
  container.appendChild(renderer.domElement);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.06;
  controls.autoRotate = true;
  controls.autoRotateSpeed = 0.4;

  // Faint axis lines.
  const axisMat = new THREE.LineBasicMaterial({ color: 0x222240, transparent: true, opacity: 0.5 });
  const axes = [[-1.5, 0, 0], [1.5, 0, 0], [0, -1.5, 0], [0, 1.5, 0], [0, 0, -1.5], [0, 0, 1.5]];
  for (let i = 0; i < axes.length; i += 2) {
    const geo = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(...axes[i]), new THREE.Vector3(...axes[i + 1]),
    ]);
    scene.add(new THREE.Line(geo, axisMat));
  }

  function onResize() {
    const ww = container.clientWidth || window.innerWidth;
    const hh = container.clientHeight || window.innerHeight;
    camera.aspect = ww / hh;
    camera.updateProjectionMatrix();
    renderer.setSize(ww, hh);
  }

  const ro = new ResizeObserver(onResize);
  ro.observe(container);

  function dispose() {
    ro.disconnect();
    renderer.dispose();
    container.removeChild(renderer.domElement);
  }

  return { scene, camera, renderer, controls, dispose };
}
