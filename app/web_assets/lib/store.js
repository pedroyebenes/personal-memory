// Tiny pub/sub store. Keys are flat (top-level state). Subscribers are notified
// when the value identity changes (no deep equality). This is enough for cross-
// view coordination: route, query, filters, selectedDocumentId, selectedConceptId.

export function createStore(initial = {}) {
  const state = { ...initial };
  const subs = new Map(); // key -> Set<fn>

  function notify(key) {
    const fns = subs.get(key);
    if (!fns) return;
    for (const fn of fns) {
      try { fn(state[key], state); } catch (err) { console.error("store listener error", err); }
    }
  }

  return {
    get(key) { return key === undefined ? state : state[key]; },

    set(patch) {
      const changed = [];
      for (const [k, v] of Object.entries(patch)) {
        if (state[k] !== v) {
          state[k] = v;
          changed.push(k);
        }
      }
      for (const k of changed) notify(k);
    },

    on(key, fn) {
      if (!subs.has(key)) subs.set(key, new Set());
      subs.get(key).add(fn);
      return () => subs.get(key)?.delete(fn);
    },

    // Subscribe to multiple keys at once; returns a single unsubscribe.
    onMany(keys, fn) {
      const offs = keys.map((k) => this.on(k, () => fn(state)));
      return () => offs.forEach((off) => off());
    },
  };
}
