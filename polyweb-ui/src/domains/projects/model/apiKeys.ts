/**
 * Project API key contracts of the browser client.
 *
 * A listed key carries metadata only. The raw key of an issue or a rotation
 * travels in `IssuedApiKey.rawKey`, separate from the metadata, so a list,
 * a store, or a draft can never hold it by accident.
 */

/** Execution scope a project API key can hold. */
export type ApiKeyScope = "search.execute" | "fetch.execute"

/** Every key scope, in display order. */
export const API_KEY_SCOPES: readonly ApiKeyScope[] = ["search.execute", "fetch.execute"]

/** Display label of each key scope. */
export const API_KEY_SCOPE_LABELS: Record<ApiKeyScope, string> = {
  "search.execute": "Search",
  "fetch.execute": "Fetch",
}

/** Derived lifecycle state of one key. */
export type ApiKeyStatus = "active" | "expired" | "revoked"

/** Safe metadata of one project API key. */
export interface ProjectApiKey {
  id: string
  project_id: string
  label: string
  prefix: string
  scopes: string[]
  created_by: string
  created_at: string
  /** `null` means the key never expires. */
  expires_at: string | null
  revoked_at: string | null
  last_used_at: string | null
  rotated_from_id: string | null
  status: ApiKeyStatus
}

/** Issue or rotation result: the metadata plus the raw key, shown once. */
export interface IssuedApiKey {
  apiKey: ProjectApiKey
  rawKey: string
}

/**
 * Expiration choice of an issue or a rotation.
 *
 * `default` omits `expires_at` (90 days on issue, the current lifetime on
 * rotation), `never` sends an explicit `null`, and `at` sends one timestamp.
 */
export type ApiKeyExpiry =
  | { kind: "default" }
  | { kind: "never" }
  | { kind: "at"; isoTimestamp: string }

/** Request of one key issue. */
export interface IssueApiKeyInput {
  label: string
  scopes: readonly ApiKeyScope[]
  expiry: ApiKeyExpiry
}

/** Request of one key rotation. */
export interface RotateApiKeyInput {
  overlapSeconds: number
  expiry: ApiKeyExpiry
}

/** Return whether an unknown value is one of the key scopes. */
export function isApiKeyScope(value: unknown): value is ApiKeyScope {
  return value === "search.execute" || value === "fetch.execute"
}
