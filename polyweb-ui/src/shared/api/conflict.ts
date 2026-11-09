import { ApiError } from "./http"

/** Code and message of one `409 {"detail": {"code", "message"}}` response. */
export interface ConflictDetail {
  code: string | null
  message: string | null
}

/** Return the conflict body of a 409 failure, or `null` for any other failure. */
export function conflictDetail(error: unknown): ConflictDetail | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null
  const body = error.raw
  const detail =
    typeof body === "object" && body !== null ? (body as { detail?: unknown }).detail : null
  if (typeof detail !== "object" || detail === null) return { code: null, message: null }
  const { code, message } = detail as { code?: unknown; message?: unknown }
  return {
    code: typeof code === "string" ? code : null,
    message: typeof message === "string" ? message : null,
  }
}

/** Return whether a failure is a 409 conflict. */
export function isConflict(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409
}

/** Return whether a failure is a 403 permission denial. */
export function isForbidden(error: unknown): boolean {
  return error instanceof ApiError && error.status === 403
}
