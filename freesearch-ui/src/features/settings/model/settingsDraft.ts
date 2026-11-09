/**
 * Pure helpers of the settings edit draft.
 *
 * A draft entry holds the value the user chose for one field; `null` means
 * "inherit" (remove this project's override). Only entries that differ from
 * the stored override are sent.
 */
import type { SettingsChanges, SettingsField, SettingsValue } from "@/domains/settings"

export type SettingsDraft = Readonly<Record<string, SettingsValue>>

function sameValue(left: SettingsValue, right: SettingsValue): boolean {
  if (Array.isArray(left) && Array.isArray(right)) {
    return left.length === right.length && left.every((item, index) => item === right[index])
  }
  return left === right
}

/**
 * Whether a draft value leaves the stored state as it is: the same override,
 * or an inherited field edited back to the value it already shows.
 */
function unchanged(value: SettingsValue, field: SettingsField): boolean {
  if (sameValue(value, field.projectOverride)) return true
  return field.projectOverride === null && sameValue(value, field.effectiveValue)
}

/** Changed fields of the whole draft, keyed by field id, ready for the write body. */
export function draftChanges(draft: SettingsDraft, fields: readonly SettingsField[]): SettingsChanges {
  const changes: Record<string, SettingsValue> = {}
  for (const field of fields) {
    if (!(field.id in draft)) continue
    const value = draft[field.id] ?? null
    if (!unchanged(value, field)) changes[field.id] = value
  }
  return changes
}

/** Return whether the draft marks one field as inherit. */
export function isInheritPending(draft: SettingsDraft, field: SettingsField): boolean {
  return field.id in draft && draft[field.id] === null && field.projectOverride !== null
}

/** Value one control shows: the draft, else the system default on inherit, else effective. */
export function controlValue(draft: SettingsDraft, field: SettingsField): SettingsValue {
  if (!(field.id in draft)) return field.effectiveValue
  const value = draft[field.id] ?? null
  return value === null ? field.systemDefault : value
}
