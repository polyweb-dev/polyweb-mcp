/**
 * Trace policy summary and the system constraints on trace options.
 *
 * The system detail is the most permissive detail allowed and the system
 * redaction is the loosest redaction allowed, so an option looser than the
 * system value is disabled with its reason, and retention is capped by the
 * system limit.
 */
import type { SettingsField } from "./settings"

export const METADATA_ONLY_REASON = "The system allows metadata only."
export const STRICT_REDACTION_REASON = "The system requires strict redaction."

function fieldById(fields: readonly SettingsField[], id: string): SettingsField | undefined {
  return fields.find((field) => field.id === id)
}

function systemCeiling(field: SettingsField): unknown {
  return field.systemLimit ?? field.systemDefault
}

/**
 * "New traces: 25% sampled, Metadata only, Strict redaction, kept 30 days."
 * Returns `null` when a trace field is missing.
 */
export function tracePolicySummary(fields: readonly SettingsField[]): string | null {
  const sampling = fieldById(fields, "trace.sampling_rate")?.effectiveValue
  const detail = fieldById(fields, "trace.detail")?.effectiveValue
  const redaction = fieldById(fields, "trace.payload_redaction")?.effectiveValue
  const retention = fieldById(fields, "trace.retention_days")?.effectiveValue
  if (typeof sampling !== "number" || typeof retention !== "number") return null
  const percent = Math.round(sampling * 1000) / 10
  const detailText = detail === "full" ? "Full payloads" : "Metadata only"
  const redactionText = redaction === "standard" ? "Standard" : "Strict"
  return `New traces: ${percent}% sampled, ${detailText}, ${redactionText} redaction, kept ${retention} days.`
}

/** Reason one enum option is disabled by the system, else `null`. */
export function disabledOptionReason(field: SettingsField, option: string): string | null {
  const ceiling = systemCeiling(field)
  if (field.id === "trace.detail" && ceiling === "metadata" && option === "full") {
    return METADATA_ONLY_REASON
  }
  if (field.id === "trace.payload_redaction" && ceiling === "strict" && option === "standard") {
    return STRICT_REDACTION_REASON
  }
  return null
}

/** Upper bound of a numeric field: the system limit when it is lower. */
export function numericMax(field: SettingsField, catalogMax: number): number {
  return typeof field.systemLimit === "number" ? Math.min(field.systemLimit, catalogMax) : catalogMax
}
