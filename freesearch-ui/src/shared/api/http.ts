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

const TIMEOUT_OR_ABORT_PATTERN = /abort|timed?\s*out|timeout/i

export function isAbortOrTimeout(error: unknown): boolean {
  if (typeof error === "string") return TIMEOUT_OR_ABORT_PATTERN.test(error)
  if (!error || typeof error !== "object") return false
  const candidate = error as { name?: unknown; message?: unknown }
  const name = typeof candidate.name === "string" ? candidate.name : ""
  const message = typeof candidate.message === "string" ? candidate.message : ""
  return TIMEOUT_OR_ABORT_PATTERN.test(`${name} ${message}`)
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

export function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.detail;
  if (isAbortOrTimeout(error)) {
    const detail =
      error && typeof error === "object" && "message" in error
        ? String((error as { message?: unknown }).message ?? "timeout")
        : "timeout";
    return statusMessage(0, detail);
  }
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}
