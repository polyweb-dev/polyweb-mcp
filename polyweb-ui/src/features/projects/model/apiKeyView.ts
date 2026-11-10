/**
 * Pure view helpers of the project API key list.
 *
 * They turn key metadata into table text. None of them ever sees a raw key:
 * the list holds metadata only.
 */
import { API_KEY_SCOPES, API_KEY_SCOPE_LABELS, isApiKeyScope } from "@/domains/projects"
import type { ApiKeyStatus, ProjectApiKey } from "@/domains/projects"
import { identityDetailLabel, identityLabel } from "@/shared/lib/identity"
import type { ContactIdentity } from "@/shared/lib/identity"

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
  const known = API_KEY_SCOPES.filter((scope) => scopes.includes(scope))
  return [...known, ...scopes.filter((scope) => !isApiKeyScope(scope))]
    .map((scope) => (isApiKeyScope(scope) ? API_KEY_SCOPE_LABELS[scope] : scope)).join(", ")
}

/**
 * Created by column text: the member display name (full name, then
 * username) when the member list is readable and holds the creator, else a
 * short id.
 */
export function creatorLabel(
  createdBy: string,
  identitiesByUserId: ReadonlyMap<string, ContactIdentity> | null
): string {
  const identity = identitiesByUserId?.get(createdBy)
  if (identity === undefined || identity === null) return createdBy.slice(0, 8)
  return identityLabel(identity)
}

/**
 * Creator contact value for disclosure: the email when it names someone the
 * primary label hides, else `null` so the primary label stands alone.
 */
export function creatorContactDetail(
  createdBy: string,
  identitiesByUserId: ReadonlyMap<string, ContactIdentity> | null
): string | null {
  const identity = identitiesByUserId?.get(createdBy)
  if (identity === undefined || identity === null) return null
  const detail = identityDetailLabel(identity)
  return detail === identityLabel(identity) ? null : detail
}

/**
 * Return whether one key can still rotate: it is active and no other key
 * names it as its predecessor (an already-rotated key only waits out its
 * overlap, and the server refuses a second rotation).
 */
export function canRotateKey(key: ProjectApiKey, keys: readonly ProjectApiKey[]): boolean {
  return key.status === "active" && !keys.some((other) => other.rotated_from_id === key.id)
}
