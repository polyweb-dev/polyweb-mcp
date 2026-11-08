/**
 * Client view of the editable settings fields: label, control kind, bounds
 * and option labels. System-only fields (section `safety_limits`) have no
 * entry and are never shown as editable rows.
 */
import type { SettingsValue } from "./settings"

export interface EnumOption {
  value: string
  label: string
}

export type FieldControl =
  | { kind: "enum"; options: readonly EnumOption[] }
  | { kind: "boolean" }
  | { kind: "number"; integer: boolean; min: number; max: number; step: number }
  | { kind: "list" }

export interface FieldSpec {
  label: string
  control: FieldControl
}

const int = (min: number, max: number): FieldControl => ({
  kind: "number",
  integer: true,
  min,
  max,
  step: 1,
})

export const DETAIL_OPTIONS: readonly EnumOption[] = [
  { value: "metadata", label: "Metadata only" },
  { value: "full", label: "Full requests" },
]

/** Editable fields by catalog id, in catalog order. */
export const FIELD_SPECS: Readonly<Record<string, FieldSpec>> = {
  "routing.fallback_policy": {
    label: "Fallback policy",
    control: {
      kind: "enum",
      options: [
        { value: "chained", label: "Chained" },
        { value: "first_only", label: "First only" },
      ],
    },
  },
  "routing.cost_optimization_preset": {
    label: "Cost preset",
    control: {
      kind: "enum",
      options: [
        { value: "balanced", label: "Balanced" },
        { value: "free_first", label: "Free first" },
      ],
    },
  },
  "routing.max_attempts": { label: "Max attempts", control: int(1, 10) },
  "routing.preferred_providers": { label: "Preferred providers", control: { kind: "list" } },
  "execution.cache_enabled": { label: "Cache", control: { kind: "boolean" } },
  "execution.default_timeout_seconds": {
    label: "Timeout (seconds)",
    control: { kind: "number", integer: false, min: 1, max: 300, step: 1 },
  },
  "execution.max_fanout_concurrency": { label: "Fan-out concurrency", control: int(1, 20) },
  "execution.cache_ttl_seconds": { label: "Cache lifetime (seconds)", control: int(0, 86400) },
  "trace.detail": { label: "Payload detail", control: { kind: "enum", options: DETAIL_OPTIONS } },
  "trace.retention_days": { label: "Retention", control: int(1, 365) },
}

/** Label of one field id, else the id itself. */
export function fieldLabel(fieldId: string): string {
  return FIELD_SPECS[fieldId]?.label ?? fieldId
}

function enumLabel(fieldId: string, value: string): string {
  const control = FIELD_SPECS[fieldId]?.control
  if (control?.kind !== "enum") return value
  return control.options.find((option) => option.value === value)?.label ?? value
}

/** Human text of one settings value. */
export function formatSettingsValue(fieldId: string, value: SettingsValue): string {
  if (value === null) return fieldId === "trace.retention_days" ? "Keep all traces" : "Inherited"
  if (typeof value === "boolean") return value ? "On" : "Off"
  if (typeof value === "number") return String(value)
  if (typeof value === "string") return enumLabel(fieldId, value)
  return value.length === 0 ? "None" : value.join(", ")
}
