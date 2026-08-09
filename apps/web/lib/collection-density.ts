export type CollectionDensity = "sparse" | "balanced" | "dense";
export type CollectionKind = "grid" | "list" | "table";

const thresholds: Record<CollectionKind, { sparseMax: number; denseMin: number }> = {
  grid: { sparseMax: 2, denseMin: 5 },
  list: { sparseMax: 3, denseMin: 8 },
  table: { sparseMax: 4, denseMin: 12 },
};

/**
 * Converts collection size into a stable editorial density tier.
 *
 * Width remains a CSS/container-query concern. This function only describes
 * how much attention and supporting copy each item can receive from the
 * collection's finite content budget.
 */
export function collectionDensity(
  count: number,
  kind: CollectionKind = "grid",
): CollectionDensity {
  const normalizedCount = Math.max(0, Math.floor(count));
  const { sparseMax, denseMin } = thresholds[kind];
  if (normalizedCount <= sparseMax) return "sparse";
  if (normalizedCount >= denseMin) return "dense";
  return "balanced";
}

/** Scalar evidence metadata fields worth exposing at each density tier. */
export function collectionDetailBudget(
  count: number,
  kind: CollectionKind = "list",
): number {
  const density = collectionDensity(count, kind);
  if (density === "sparse") return 8;
  if (density === "balanced") return 4;
  return 2;
}
