/**
 * Project settings resolution: per-field effective value, provenance, the
 * system default and the system limit, plus the revision-bound copy plan.
 */

export type SettingsSectionId = "routing" | "execution" | "trace"
export const SETTINGS_SECTIONS: readonly SettingsSectionId[] = ["routing", "execution", "trace"]

export const SECTION_TITLES: Record<SettingsSectionId, string> = {
  routing: "Routing",
  execution: "Execution",
  trace: "Trace policy",
}

export type SettingsProvenance = "system_default" | "project_override" | "system_constrained"
export const SETTINGS_PROVENANCES: readonly SettingsProvenance[] = [
  "system_default",
  "project_override",
  "system_constrained",
]

export const PROVENANCE_LABELS: Record<SettingsProvenance, string> = {
  system_default: "System default",
  project_override: "Project override",
  system_constrained: "Limited by system",
}

/** One JSON settings value; `null` means inherit. */
export type SettingsValue = string | number | boolean | readonly string[] | null

/** Resolution of one settings field. */
export interface SettingsField {
  /** Catalog id, e.g. `trace.retention_days`. */
  id: string
  section: string
  attribute: string
  effectiveValue: SettingsValue
  provenance: SettingsProvenance
  systemDefault: SettingsValue
  projectOverride: SettingsValue
  overrideAllowed: boolean
  systemLimit: SettingsValue
  constraintApplied: boolean
}

/** Resolved settings of one project and the revisions that produced it. */
export interface ProjectSettings {
  fields: SettingsField[]
  systemRevision: number
  projectRevision: number
}

/** Changed fields keyed by field id; `null` resets one override (inherit). */
export type SettingsChanges = Readonly<Record<string, SettingsValue>>

export type CopyMode = "overrides_only" | "effective_snapshot"
export const COPY_MODES: readonly CopyMode[] = ["overrides_only", "effective_snapshot"]

export interface CopyField {
  fieldId: string
  section: string
  attribute: string
  provenance: SettingsProvenance
  value: SettingsValue
  changed: boolean
  constraintApplied: boolean
}

export interface CopyRejection {
  fieldId: string
  reason: string
}

export interface CopyBinding {
  bindingId: string
  credentialId: string
  routeLabel: string
  version: number
  selected: boolean
  eligible: boolean
  rejection: string | null
}

/** The revision-bound plan a preview returns. */
export interface CopyPlan {
  sourceProjectId: string
  targetProjectId: string
  mode: CopyMode
  sourceRevision: number
  targetRevision: number
  systemRevision: number
  fields: CopyField[]
  rejected: CopyRejection[]
  bindings: CopyBinding[]
}

/** One copy request: the source, the mode, three revisions and the bindings. */
export interface CopyRequest {
  sourceProjectId: string
  mode: CopyMode
  sourceRevision: number
  targetRevision: number
  systemRevision: number
  /** Selected binding versions keyed by binding id. */
  bindingVersions: Readonly<Record<string, number>>
}

/** Result of an applied copy. */
export interface CopyResult {
  plan: CopyPlan
  settings: ProjectSettings
  bindingsCopied: string[]
}

/** Return the catalog section of one field id (`trace.detail` → `trace`). */
export function sectionOfField(fieldId: string): string {
  return fieldId.split(".")[0] ?? ""
}
