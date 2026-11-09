import { requestJson } from "@/shared/api/client"
import { ApiError } from "@/shared/api/http"

export interface PermissionCatalogEntry {
  key: string
  bit: number
  action: string
  group: string
  developer_toggle: boolean
  label: string
  description: string
}

export interface PermissionCatalogPreset {
  key: string
  label: string
  permissions: number
}

export interface PermissionCatalog {
  permissions: PermissionCatalogEntry[]
  presets: PermissionCatalogPreset[]
}

export function decodeProjectPermissionCatalog(value: unknown): PermissionCatalog {
  if (typeof value !== "object" || value === null || !("permissions" in value) || !Array.isArray(value.permissions) ||
      !("presets" in value) || !Array.isArray(value.presets)) {
    throw new ApiError(0, "The server returned an unexpected permission catalog.", value)
  }
  const validEntry = (entry: unknown): entry is PermissionCatalogEntry => {
    if (typeof entry !== "object" || entry === null || Array.isArray(entry)) return false
    const fields = entry as Record<string, unknown>
    return ["key", "action", "group", "label", "description"].every((key) => typeof fields[key] === "string") &&
      typeof fields.bit === "number" && typeof fields.developer_toggle === "boolean"
  }
  const validPreset = (preset: unknown): preset is PermissionCatalogPreset =>
    typeof preset === "object" && preset !== null && "key" in preset && typeof preset.key === "string" &&
    "label" in preset && typeof preset.label === "string" && "permissions" in preset && typeof preset.permissions === "number"
  if (!value.permissions.every(validEntry) || !value.presets.every(validPreset)) {
    throw new ApiError(0, "The server returned an unexpected permission catalog.", value)
  }
  return { permissions: value.permissions, presets: value.presets }
}

export async function getProjectPermissionCatalog(signal?: AbortSignal): Promise<PermissionCatalog> {
  return decodeProjectPermissionCatalog(await requestJson<unknown>("/api/v1/permissions/project-catalog", { signal }))
}
