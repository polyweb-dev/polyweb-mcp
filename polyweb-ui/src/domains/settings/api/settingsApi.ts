/**
 * Project settings routes: resolution read, revision-bound write, and the
 * revision-bound copy preview and apply.
 */
import { requestJson } from "@/shared/api/client"
import { asRecord } from "@/shared/api/decode"
import { decodeCopyPlan, decodeProjectSettings } from "./settingsWire"
import { sectionOfField } from "../model/settings"
import type {
  CopyPlan,
  CopyRequest,
  CopyResult,
  ProjectSettings,
  SettingsChanges,
} from "../model/settings"

function settingsPath(projectId: string): string {
  return `/api/v1/projects/${encodeURIComponent(projectId)}/settings`
}

/** Read the resolved settings of one project. */
export async function getProjectSettings(
  projectId: string,
  signal?: AbortSignal
): Promise<ProjectSettings> {
  const payload = await requestJson<unknown>(
    settingsPath(projectId),
    signal === undefined ? {} : { signal }
  )
  return decodeProjectSettings(payload)
}

/**
 * Build the `ProjectSettingsUpdate` body: only the changed fields, grouped by
 * section, with `null` resetting one override, at the expected revision.
 */
export function settingsUpdateBody(
  changes: SettingsChanges,
  expectedRevision: number
): Record<string, unknown> {
  const body: Record<string, unknown> = { expected_revision: expectedRevision }
  for (const [fieldId, value] of Object.entries(changes)) {
    const section = sectionOfField(fieldId)
    const attribute = fieldId.slice(section.length + 1)
    const current = asRecord(body[section]) ?? {}
    body[section] = { ...current, [attribute]: value }
  }
  return body
}

/** Write changed fields at one expected revision; a stale revision answers 409. */
export async function updateProjectSettings(
  projectId: string,
  changes: SettingsChanges,
  expectedRevision: number
): Promise<ProjectSettings> {
  const payload = await requestJson<unknown>(settingsPath(projectId), {
    method: "PUT",
    body: JSON.stringify(settingsUpdateBody(changes, expectedRevision)),
  })
  return decodeProjectSettings(payload)
}

function copyBody(request: CopyRequest): string {
  return JSON.stringify({
    source_project_id: request.sourceProjectId,
    expected_source_revision: request.sourceRevision,
    expected_target_revision: request.targetRevision,
    expected_system_revision: request.systemRevision,
    mode: request.mode,
    binding_versions: { ...request.bindingVersions },
  })
}

/** Preview one copy into the target project; nothing is written. */
export async function previewSettingsCopy(
  targetProjectId: string,
  request: CopyRequest,
  signal?: AbortSignal
): Promise<CopyPlan> {
  const payload = await requestJson<unknown>(`${settingsPath(targetProjectId)}/copy/preview`, {
    method: "POST",
    body: copyBody(request),
    ...(signal === undefined ? {} : { signal }),
  })
  return decodeCopyPlan(payload)
}

/** Apply one previewed copy; it must echo the preview's three revisions. */
export async function applySettingsCopy(
  targetProjectId: string,
  request: CopyRequest
): Promise<CopyResult> {
  const payload = await requestJson<unknown>(`${settingsPath(targetProjectId)}/copy`, {
    method: "POST",
    body: copyBody(request),
  })
  const record = asRecord(payload)
  const copied = Array.isArray(record?.bindings_copied) ? record.bindings_copied : []
  return {
    plan: decodeCopyPlan(payload),
    settings: decodeProjectSettings(record?.target),
    bindingsCopied: copied.filter((id): id is string => typeof id === "string"),
  }
}
