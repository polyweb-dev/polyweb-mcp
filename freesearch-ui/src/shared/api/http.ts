// Shared transport-generic HTTP error normalization (no domain imports).
import type { BackendValidationErrorItem } from "@/shared/api/validationWire"

export class ApiError extends Error {
  readonly status: number
  readonly detail: string
  readonly raw: unknown

  constructor(status: number, detail: string, raw: unknown) {
    super(detail)
    this.name = "ApiError"
    this.status = status
    this.detail = detail
    this.raw = raw
  }
}

function compactJson(value: unknown): string {
  try {
    const json = JSON.stringify(value)
    if (json && json !== "{}") return json.length > 300 ? `${json.slice(0, 297)}...` : json
  } catch {
    // Fall through to a stable human-readable message for unserialisable bodies.
  }
  return "Unknown API error"
}

export function parseDetail(body: unknown): string {
  if (typeof body === "string" && body.trim()) return body

  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail?: unknown }).detail
    if (typeof detail === "string" && detail.trim()) return detail
    if (Array.isArray(detail)) {
      const items = detail
        .filter((item): item is BackendValidationErrorItem => Boolean(item && typeof item === "object"))
        .map((item) => {
          const loc = Array.isArray(item.loc) ? item.loc.join(".") : "detail"
          const message = typeof item.msg === "string" ? item.msg : compactJson(item.msg)
          return `${loc}: ${message}`
        })
      if (items.length > 0) return items.join("; ")
    }
  }

  return compactJson(body)
}

export function isAbortOrTimeout(error: unknown): boolean {
  if (typeof error === "string") return /abort|timeout/i.test(error)
  if (!error || typeof error !== "object") return false
  const candidate = error as { name?: unknown; message?: unknown; cause?: unknown }
  const name = typeof candidate.name === "string" ? candidate.name : ""
  const message = typeof candidate.message === "string" ? candidate.message : ""
  const cause =
    candidate.cause && typeof candidate.cause === "object"
      ? `${(candidate.cause as { name?: unknown }).name ?? ""} ${(candidate.cause as { message?: unknown }).message ?? ""}`
      : typeof candidate.cause === "string"
        ? candidate.cause
        : ""
  return /abort|timeout/i.test(`${name} ${message} ${cause}`)
}

export function statusMessage(status: number, detail: string): string {
  if (isAbortOrTimeout(detail)) return "Request timed out; please try again"
  const suffix = detail ? `: ${detail}` : ""
  if (status === 0) return `API unreachable; check the Vite proxy and backend server${suffix}`
  if (status === 404) return `API resource not found${suffix}`
  if (status === 422) return `Invalid API request${suffix}`
  if (status === 503) return `API temporarily unavailable; try again${suffix}`
  if (status >= 500) return `API server error${suffix}`
  if (status >= 400) return `API request failed${suffix}`
  return `API response error${suffix}`
}
/** Map a transport failure to ApiError (ApiError passes through). Always throws. */
export function toApiError(error: unknown): never {
  if (error instanceof ApiError) throw error;
  if (isAbortOrTimeout(error)) {
    const detail =
      error && typeof error === "object" && "message" in error
        ? String((error as { message?: unknown }).message ?? "timeout")
        : "timeout";
    throw new ApiError(0, statusMessage(0, detail), error);
  }
  if (error instanceof TypeError) {
    throw new ApiError(0, statusMessage(0, error.message), error);
  }
  throw error;
}

export function prettifyErrorMessage(message: string): string {
  if (!message || typeof message !== "string") return message

  // 1. All search providers unconfigured or disabled
  if (/no provider is configured/i.test(message)) {
    return "no provider is configured: please add an API key in Settings → Keys or enable a provider in Settings → Providers."
  }

  // 2. Specific provider not configured
  const providerMatch = message.match(/provider\s+([a-z0-9_-]+)\s+is\s+not\s+configured/i)
  if (providerMatch) {
    const pName = providerMatch[1]
    return `provider "${pName}" is not configured: please add an API key in Settings → Keys.`
  }

  // 3. Provider eligibility routing failure
  if (/no (?:required )?provider is eligible/i.test(message)) {
    return "The selected provider is currently unavailable or disabled. Check its status in Settings → Providers."
  }

  // 4. Timeouts & signal aborts
  if (isAbortOrTimeout(message) || /signal timed out/i.test(message)) {
    return "The request timed out. The provider or target site took too long to respond. Please try again."
  }

  // 5. Anti-bot / scraper blocks
  if (/bot_blocked/i.test(message) || /blocked by anti-bot/i.test(message)) {
    return "Extraction blocked: The target website has anti-bot protection blocking automated access."
  }

  // 6. Generic cleanup of any remaining raw HTTP paths like (PUT /api/v1/...) or (GET /api/v1/...)
  const sanitized = message.replace(/\s*\((?:GET|POST|PUT|PATCH|DELETE)\s+\/api\/[^)]+\)/gi, "")

  return sanitized
}

export function errorMessage(error: unknown, fallback: string): string {
  let raw: string
  if (error instanceof ApiError) {
    raw = error.detail
  } else if (isAbortOrTimeout(error)) {
    const detail =
      error && typeof error === "object" && "message" in error
        ? String((error as { message?: unknown }).message ?? "timeout")
        : "timeout"
    raw = statusMessage(0, detail)
  } else if (error instanceof Error && error.message) {
    raw = error.message
  } else {
    raw = fallback
  }
  return prettifyErrorMessage(raw)
}
