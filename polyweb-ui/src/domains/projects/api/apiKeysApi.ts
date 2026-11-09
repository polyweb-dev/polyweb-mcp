/**
 * Project API key routes of the backend.
 *
 * Every call goes through the shared transport and decodes its payload from
 * `unknown`. The raw key of an issue or a rotation returns to the caller once
 * and is never logged, cached, or stored by this module.
 */
import { requestJson } from "@/shared/api/client"
import { ApiError } from "@/shared/api/http"
import type {
  ApiKeyExpiry,
  IssueApiKeyInput,
  IssuedApiKey,
  ProjectApiKey,
  RotateApiKeyInput,
} from "../model/apiKeys"
import { decodeIssuedApiKey, decodeProjectApiKeyList } from "./apiKeysWire"
import { PERMISSION_LOST_MESSAGE, projectConflictCode } from "./projectsApi"

const BASE = "/api/v1/projects"

/** User-facing copy of the mapped key failures. */
export const API_KEY_INACTIVE_MESSAGE = "This key is no longer active."
export const PROJECT_ARCHIVED_KEYS_MESSAGE = "An archived project cannot issue or rotate keys."

const CONFLICT_MESSAGES: Record<string, string> = {
  API_KEY_INACTIVE: API_KEY_INACTIVE_MESSAGE,
  PROJECT_ARCHIVED: PROJECT_ARCHIVED_KEYS_MESSAGE,
}

/**
 * Map a key mutation failure to safe user-facing copy.
 *
 * A known conflict keeps its own message, a 403 means the caller lost the
 * permission, and a 422 shows the server's validation detail.
 */
export function apiKeyMutationMessage(error: unknown, fallback: string): string {
  const code = projectConflictCode(error)
  const conflict = code === null ? undefined : CONFLICT_MESSAGES[code]
  if (conflict !== undefined) return conflict
  if (!(error instanceof ApiError)) return fallback
  if (error.status === 403) return PERMISSION_LOST_MESSAGE
  if (error.status === 422 && error.detail) return error.detail
  return fallback
}

/** Write the expiration choice into one request body; `default` omits the field. */
function withExpiry(body: Record<string, unknown>, expiry: ApiKeyExpiry): Record<string, unknown> {
  if (expiry.kind === "never") return { ...body, expires_at: null }
  if (expiry.kind === "at") return { ...body, expires_at: expiry.isoTimestamp }
  return body
}

/** Return the key metadata of one project. */
export async function listProjectApiKeys(
  projectId: string,
  signal: AbortSignal
): Promise<ProjectApiKey[]> {
  return decodeProjectApiKeyList(
    await requestJson<unknown>(`${BASE}/${projectId}/api-keys`, { signal })
  )
}

/** Issue one key; the result carries the raw key exactly once. */
export async function issueProjectApiKey(
  projectId: string,
  input: IssueApiKeyInput
): Promise<IssuedApiKey> {
  const body = withExpiry({ label: input.label, scopes: [...input.scopes] }, input.expiry)
  return decodeIssuedApiKey(
    await requestJson<unknown>(`${BASE}/${projectId}/api-keys`, {
      method: "POST",
      body: JSON.stringify(body),
    })
  )
}

/** Rotate one active key; the result carries the new raw key exactly once. */
export async function rotateProjectApiKey(
  projectId: string,
  keyId: string,
  input: RotateApiKeyInput
): Promise<IssuedApiKey> {
  const body = withExpiry({ overlap_seconds: input.overlapSeconds }, input.expiry)
  return decodeIssuedApiKey(
    await requestJson<unknown>(`${BASE}/${projectId}/api-keys/${keyId}/rotate`, {
      method: "POST",
      body: JSON.stringify(body),
    })
  )
}

/** Revoke one key; a repeated revoke changes nothing on the server. */
export async function revokeProjectApiKey(projectId: string, keyId: string): Promise<void> {
  await requestJson<unknown>(`${BASE}/${projectId}/api-keys/${keyId}`, { method: "DELETE" })
}
