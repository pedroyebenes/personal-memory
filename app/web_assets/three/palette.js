// Cluster + supercluster color palettes used across the map view.

export const PALETTE = [
  "#e05c7a", "#4fc3a1", "#f6a623", "#7b9fd4", "#c47bc1",
  "#80c770", "#f0886a", "#5dbcd2", "#d4af37", "#9b8eb8",
  "#e8834e", "#52b8d8", "#76b9a6", "#b8cc6c", "#d47da9",
  "#6a9fc0", "#e0a060", "#8a7fc8", "#68c890", "#d06060",
];

export const SUPER_PALETTE = [
  "#8fb6a2", "#c79d6a", "#a78bb8", "#6f9fc0", "#d89595",
  "#b5ad6a", "#88a8b0", "#a68fa0", "#7fa890", "#c79070",
];

export const NOISE_COLOR = "#55556a";

export function clusterColor(id, vizData) {
  const summary = vizData?.clusters?.find((c) => c.id === id);
  if (summary?.is_noise) return NOISE_COLOR;
  return PALETTE[id % PALETTE.length];
}

export function superclusterColor(id, vizData) {
  const summary = vizData?.superclusters?.find((c) => c.id === id);
  if (summary?.is_noise) return NOISE_COLOR;
  return SUPER_PALETTE[id % SUPER_PALETTE.length];
}

export function clusterSummary(id, vizData) {
  return vizData?.clusters?.find((c) => c.id === id) || { id, name: `Cluster ${id + 1}`, size: 0 };
}

export function displayConceptTitle(p) {
  const c = p.top_concept?.canonical_name?.trim();
  if (c) return c;
  const t = (p.document_title || "").trim();
  return t || "Untitled";
}
