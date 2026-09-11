/**
 * Canonical aggregation dimension from the backend (QUOTA.md Option A).
 * Logic branches on this, never on display text. `null` = legacy/unknown:
 * rows recorded before canonical units existed; never merged into a
 * known dimension and never summed across kinds.
 */
export type UnitKind = "REQUEST" | "CREDIT" | "USD" | "FREE";

/** Canonical unit dimension (QUOTA.md Option A). Uppercase on the wire; null/absent = legacy. */
export type BackendUnitKind = "REQUEST" | "CREDIT" | "USD" | "FREE";

/** Normalize wire unit_kind (uppercase) to the UI UnitKind; unknown/absent → null (legacy). */
export function normalizeUnitKind(value: unknown): UnitKind | null {
  if (typeof value !== "string") return null;
  const upper = value.toUpperCase() as UnitKind;
  return upper === "REQUEST" || upper === "CREDIT" || upper === "USD" || upper === "FREE"
    ? upper
    : null;
}

/** Presentation label for a unit dimension. Logic must branch on unitKind, never this text. */
export function unitLabel(unitKind: UnitKind | null, displayUnit?: string | null): string {
  if (displayUnit) return displayUnit;
  switch (unitKind) {
    case "REQUEST":
      return "requests";
    case "CREDIT":
      return "credits";
    case "USD":
      return "USD";
    case "FREE":
      return "free";
    default:
      return "legacy";
  }
}
