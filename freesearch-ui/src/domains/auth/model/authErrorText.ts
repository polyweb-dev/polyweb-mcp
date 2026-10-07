/**
 * Friendly text for one failed account request.
 *
 * The auth screens never show a raw server body. One known error code or one
 * known safe server sentence becomes a short friendly sentence, an object body
 * becomes a status sentence, and an unknown plain sentence passes through
 * because the server already keeps it safe. A limited request keeps its wait
 * hint, which is a plain sentence from the transport.
 */
import { ApiError, errorMessage } from "@/shared/api/http"

/** Friendly sentence of each auth error code. */
const CODE_TEXT: Record<string, string> = {
  REGISTER_INVALID_PASSWORD:
    "Use 12 to 128 characters with an upper-case letter, a lower-case letter, a digit, and a symbol.",
  REGISTER_USER_ALREADY_EXISTS: "That email address already has an account. Sign in instead.",
  LOGIN_BAD_CREDENTIALS: "The email address or the password is not correct.",
}

/** Friendly sentence of each current safe server detail. */
const DETAIL_TEXT: Record<string, string> = {
  "invalid authentication request": "Check the email address and the password rule.",
  "not authenticated": "Your session ended. Sign in again.",
  "browser request rejected": "This request was rejected. Reload the page and try again.",
  "account authentication is not configured":
    "Sign-in is not ready yet. Set FREESEARCH_AUTH_JWT_SECRET on the server, then restart the API.",
  "authentication is temporarily unavailable":
    "The account service is unavailable. Try again in a moment.",
}

/** Return the friendly sentence of one code or detail, or `null` for none. */
function friendlyText(value: string): string | null {
  return CODE_TEXT[value] ?? DETAIL_TEXT[value] ?? null
}

/** Return whether one detail is a serialized body rather than a sentence. */
function isSerializedBody(detail: string): boolean {
  const text = detail.trim()
  return text.startsWith("{") || text.startsWith("[")
}

/** Return the friendly sentence of one failure status, or `null` for none. */
function statusText(status: number): string | null {
  if (status === 401) return DETAIL_TEXT["not authenticated"] ?? null
  if (status === 403) return DETAIL_TEXT["browser request rejected"] ?? null
  if (status === 422) return DETAIL_TEXT["invalid authentication request"] ?? null
  if (status >= 500) return DETAIL_TEXT["authentication is temporarily unavailable"] ?? null
  return null
}

/** Return the friendly sentence of one error body, or `null` for an unknown one. */
function knownText(raw: unknown): string | null {
  if (typeof raw === "string") return friendlyText(raw)
  if (typeof raw !== "object" || raw === null) return null
  const detail = (raw as { detail?: unknown }).detail
  if (typeof detail === "string") return friendlyText(detail)
  if (typeof detail !== "object" || detail === null) return null
  const code = (detail as { code?: unknown }).code
  return typeof code === "string" ? friendlyText(code) : null
}

/** Return the friendly, credential-free text of one failed account request. */
export function authErrorText(error: unknown, fallback: string): string {
  if (!(error instanceof ApiError)) return errorMessage(error, fallback)
  const known = knownText(error.raw)
  if (known !== null) return known
  if (error.status === 429) return error.detail
  if (isSerializedBody(error.detail)) return statusText(error.status) ?? fallback
  return error.detail
}
