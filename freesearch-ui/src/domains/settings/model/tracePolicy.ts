/**
 * The system constraints on trace options.
 *
 * System detail is the ceiling and retention is capped by the system limit.
 */
import type { SettingsField } from "./settings"

export const METADATA_ONLY_REASON = "The system limit is metadata only."

function systemCeiling(field: SettingsField): unknown {
  return field.systemLimit ?? field.systemDefault
}

/** Reason one enum option is disabled by the system, else `null`. */
export function disabledOptionReason(field: SettingsField, option: string): string | null {
  const ceiling = systemCeiling(field)
  if (field.id === "trace.detail" && ceiling === "metadata" && option === "full") {
    return METADATA_ONLY_REASON
  }
  return null
}

/** Upper bound of a numeric field: the system limit when it is lower. */
export function numericMax(field: SettingsField, catalogMax: number): number {
  return typeof field.systemLimit === "number" ? Math.min(field.systemLimit, catalogMax) : catalogMax
}
