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

/** Changed fields of one section, keyed by field id, ready for the write body. */
export function sectionChanges(
  draft: SettingsDraft,
  fields: readonly SettingsField[],
  section: string
): SettingsChanges {
  const changes: Record<string, SettingsValue> = {}
  for (const field of fields) {
    if (field.section !== section || !(field.id in draft)) continue
    const value = draft[field.id] ?? null
    if (!sameValue(value, field.projectOverride)) changes[field.id] = value
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

/** Draft without the entries of one section. */
export function withoutSection(
  draft: SettingsDraft,
  fields: readonly SettingsField[],
  section: string
): SettingsDraft {
  const ids = new Set(fields.filter((field) => field.section === section).map((field) => field.id))
  return Object.fromEntries(Object.entries(draft).filter(([id]) => !ids.has(id)))
}

/** Parse the comma-separated provider list of the preferred providers field. */
export function parseList(text: string): string[] {
  return text
    .split(",")
    .map((item) => item.trim())
    .filter((item) => item !== "")
}
