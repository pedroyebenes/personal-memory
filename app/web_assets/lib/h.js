// h(tag, attrs, children) — minimal DOM builder.
//
// Conventions:
//   - `class` sets className.
//   - `style` accepts an object of CSS properties.
//   - Keys starting with `on` (e.g. `onclick`) bind event listeners.
//   - `dataset` accepts an object whose keys become data-* attributes.
//   - `html` is an explicit opt-in for innerHTML (use sparingly).
//   - Boolean true sets the attribute; false / null / undefined skip it.
//   - Children may be Nodes, primitives (coerced to text), or null/false (skipped).

export function h(tag, attrs, children) {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === false || v == null) continue;
      if (k === "class") el.className = v;
      else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
      else if (k === "dataset" && typeof v === "object") {
        for (const [dk, dv] of Object.entries(v)) {
          if (dv != null) el.dataset[dk] = String(dv);
        }
      } else if (k === "html") el.innerHTML = v;
      else if (k.startsWith("on") && typeof v === "function") {
        el.addEventListener(k.slice(2).toLowerCase(), v);
      } else if (v === true) el.setAttribute(k, "");
      else el.setAttribute(k, v);
    }
  }
  if (children != null) {
    const list = Array.isArray(children) ? children : [children];
    for (const c of list) {
      if (c == null || c === false) continue;
      el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
    }
  }
  return el;
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

export function mount(target, ...nodes) {
  clear(target);
  for (const n of nodes) {
    if (n != null) target.appendChild(n instanceof Node ? n : document.createTextNode(String(n)));
  }
}
