/**
 * Pure view helpers of the project API key list.
 *
 * They turn key metadata into table text. None of them ever sees a raw key:
 * the list holds metadata only.
 */
import { API_KEY_SCOPE_LABELS, isApiKeyScope } from "@/domains/projects"
import type { ApiKeyStatus, ProjectApiKey } from "@/domains/projects"

const STATUS_LABELS: Record<ApiKeyStatus, string> = {
  active: "Active",
  expired: "Expired",
  revoked: "Revoked",
}

/** Return the keys newest first, without mutating the input. */
export function sortNewestFirst(keys: readonly ProjectApiKey[]): ProjectApiKey[] {
  return [...keys].sort((left, right) => Date.parse(right.created_at) - Date.parse(left.created_at))
}

/** Format one timestamp as a short local date, or return the raw text. */
export function formatKeyDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })
}

/** Status column text. */
export function statusLabel(status: ApiKeyStatus): string {
  return STATUS_LABELS[status]
}

/** Expires column text: `null` means the key never expires. */
export function expiresLabel(key: ProjectApiKey): string {
  return key.expires_at === null ? "No expiration" : formatKeyDate(key.expires_at)
}

/** Last used column text: `null` means the key was never used. */
export function lastUsedLabel(key: ProjectApiKey): string {
  return key.last_used_at === null ? "Never" : formatKeyDate(key.last_used_at)
}

/** Scopes column text, with display labels for the known scopes. */
export function scopesLabel(scopes: readonly string[]): string {
  return scopes.map((scope) => (isApiKeyScope(scope) ? API_KEY_SCOPE_LABELS[scope] : scope)).join(", ")
}

/** Operation tag text of one scope list: `search.execute` → `search`. */
export function scopeOperations(scopes: readonly string[]): readonly string[] {
  return scopes.map((scope) => scope.replace(/\.execute$/, ""))
}

/**
 * Created by column text: the member email when the member list is readable
 * and holds the creator, else a short id.
 */
export function creatorLabel(
  createdBy: string,
  emailsByUserId: ReadonlyMap<string, string> | null
): string {
  return emailsByUserId?.get(createdBy) ?? createdBy.slice(0, 8)
}

/**
 * Return whether one key can still rotate: it is active and no other key
 * names it as its predecessor (an already-rotated key only waits out its
 * overlap, and the server refuses a second rotation).
 */
export function canRotateKey(key: ProjectApiKey, keys: readonly ProjectApiKey[]): boolean {
  return key.status === "active" && !keys.some((other) => other.rotated_from_id === key.id)
}
