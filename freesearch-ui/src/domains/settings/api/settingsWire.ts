/**
 * Decoders of settings resolution and copy plan payloads. Only the named
 * fields are copied; values must be plain JSON scalars or string lists.
 */
import {
  asRecord,
  readEnum,
  readFlag,
  readInt,
  readString,
  type JsonRecord,
} from "@/shared/api/decode"
import { COPY_MODES, SETTINGS_PROVENANCES, SETTINGS_SECTIONS, sectionOfField } from "../model/settings"
import type {
  CopyBinding,
  CopyField,
  CopyPlan,
  CopyRejection,
  ProjectSettings,
  SettingsField,
  SettingsValue,
} from "../model/settings"

/** Decode one settings value; anything that is not a scalar or string list is `null`. */
export function decodeSettingsValue(value: unknown): SettingsValue {
  if (typeof value === "string" || typeof value === "boolean") return value
  if (typeof value === "number" && Number.isFinite(value)) return value
  if (Array.isArray(value) && value.every((item) => typeof item === "string")) {
    return value as string[]
  }
  return null
}

function isProjectSection(section: string): boolean {
  return (SETTINGS_SECTIONS as readonly string[]).includes(section)
}

function decodeField(id: string, value: unknown): SettingsField | null {
  const record = asRecord(value)
  if (record === null) return null
  const provenance = readEnum(record, "provenance", SETTINGS_PROVENANCES)
  const section = readString(record, "section") || sectionOfField(id)
  if (provenance === null || !isProjectSection(section)) return null
  return {
    id,
    section,
    attribute: id.slice(id.indexOf(".") + 1),
    effectiveValue: decodeSettingsValue(record.effective_value),
    provenance,
    systemDefault: decodeSettingsValue(record.system_default),
    projectOverride: decodeSettingsValue(record.project_override),
    overrideAllowed: record.override_allowed !== false,
    systemLimit: decodeSettingsValue(record.system_safety_limit),
    constraintApplied: readFlag(record, "constraint_applied"),
  }
}

function decodeFields(record: JsonRecord): SettingsField[] {
  const fields = asRecord(record.fields)
  if (fields === null) return []
  const decoded: SettingsField[] = []
  for (const [id, value] of Object.entries(fields)) {
    const field = decodeField(id, value)
    if (field !== null) decoded.push(field)
  }
  return decoded
}

/** Decode `SettingsResolution`; system-only fields are dropped. */
export function decodeProjectSettings(payload: unknown): ProjectSettings {
  const record = asRecord(payload)
  const systemRevision = record === null ? null : readInt(record, "system_revision")
  if (record === null || systemRevision === null) throw new Error("settings could not be read")
  return {
    fields: decodeFields(record),
    systemRevision,
    projectRevision: readInt(record, "project_revision") ?? 0,
  }
}

function decodeCopyField(value: unknown): CopyField | null {
  const record = asRecord(value)
  if (record === null) return null
  const fieldId = readString(record, "field_id")
  const provenance = readEnum(record, "provenance", SETTINGS_PROVENANCES)
  if (fieldId === null || provenance === null) return null
  return {
    fieldId,
    section: readString(record, "section") ?? sectionOfField(fieldId),
    attribute: readString(record, "attribute") ?? fieldId,
    provenance,
    value: decodeSettingsValue(record.value),
    changed: readFlag(record, "changed"),
    constraintApplied: readFlag(record, "constraint_applied"),
  }
}

function decodeRejection(value: unknown): CopyRejection | null {
  const record = asRecord(value)
  if (record === null) return null
  const fieldId = readString(record, "field_id")
  const reason = readString(record, "reason")
  return fieldId === null || reason === null ? null : { fieldId, reason }
}

function decodeCopyBinding(value: unknown): CopyBinding | null {
  const record = asRecord(value)
  if (record === null) return null
  const bindingId = readString(record, "binding_id")
  const version = readInt(record, "version")
  if (bindingId === null || version === null) return null
  return {
    bindingId,
    credentialId: readString(record, "credential_id") ?? "",
    routeLabel: readString(record, "route_label") ?? bindingId,
    version,
    selected: readFlag(record, "selected"),
    eligible: readFlag(record, "eligible"),
    rejection: readString(record, "rejection"),
  }
}

function rows<T>(value: unknown, decode: (row: unknown) => T | null): T[] {
  if (!Array.isArray(value)) return []
  return value.map(decode).filter((row): row is T => row !== null)
}

/** Decode the plan part of a copy preview or result. */
export function decodeCopyPlan(payload: unknown): CopyPlan {
  const record = asRecord(payload)
  const mode = record === null ? null : readEnum(record, "mode", COPY_MODES)
  const source = record === null ? null : readInt(record, "source_revision")
  const target = record === null ? null : readInt(record, "target_revision")
  const system = record === null ? null : readInt(record, "system_revision")
  if (record === null || mode === null || source === null || target === null || system === null) {
    throw new Error("settings copy plan could not be read")
  }
  return {
    sourceProjectId: readString(record, "source_project_id") ?? "",
    targetProjectId: readString(record, "target_project_id") ?? "",
    mode,
    sourceRevision: source,
    targetRevision: target,
    systemRevision: system,
    fields: rows(record.fields, decodeCopyField),
    rejected: rows(record.rejected, decodeRejection),
    bindings: rows(record.bindings, decodeCopyBinding),
  }
}
