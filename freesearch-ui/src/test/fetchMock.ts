import { vi } from "vitest"

/**
 * Shared fetch-stub infrastructure for the live-backend integration tests.
 *
 * Every test stubs the global `fetch` (same-origin relative paths only — the
 * app must never call an absolute http://127.0.0.1:8001 literal) and records
 * each request for exact method / URL / JSON-body assertions.
 */

export interface RecordedRequest {
  url: string
  method: string
  headers: Record<string, string>
  bodyText: string | undefined
  body: unknown
  signal: AbortSignal | null
}

/** 200 JSON response carrying a snake_case backend wire payload. */
export function ok(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

/** Non-2xx JSON error response (`{detail: string}` or FastAPI 422 shape). */
export function err(status: number, body: unknown): Response {
  return ok(body, status)
}

export type FetchHandler = (req: RecordedRequest) => Response | Promise<Response>

export interface FetchStub {
  fetchMock: ReturnType<typeof vi.fn>
  requests: RecordedRequest[]
  requestsTo(urlMatch: string | RegExp): RecordedRequest[]
}

function parseBodyText(bodyText: string | undefined): unknown {
  if (bodyText === undefined) return undefined
  try {
    return JSON.parse(bodyText)
  } catch {
    return bodyText
  }
}

function normalizeHeaders(raw: HeadersInit | undefined): Record<string, string> {
  const headers: Record<string, string> = {}
  if (raw instanceof Headers) {
    raw.forEach((value, key) => {
      headers[key] = value
    })
  } else if (Array.isArray(raw)) {
    for (const [key, value] of raw) headers[key] = value
  } else if (raw) {
    Object.assign(headers, raw)
  }
  return headers
}

function toRecordedRequest(input: unknown, init?: RequestInit): RecordedRequest {
  const url = typeof input === "string" ? input : String(input)
  const bodyText = typeof init?.body === "string" ? init.body : undefined
  const body = parseBodyText(bodyText)
  const headers = normalizeHeaders(init?.headers)
  return {
    url,
    method: (init?.method ?? "GET").toUpperCase(),
    headers,
    bodyText,
    body,
    signal: (init?.signal as AbortSignal | null | undefined) ?? null,
  }
}

export function installFetchStub(handler: FetchHandler): FetchStub {
  const requests: RecordedRequest[] = []
  const fetchMock = vi.fn(async (input: unknown, init?: RequestInit) => {
    const req = toRecordedRequest(input, init)
    requests.push(req)
    return handler(req)
  })
  vi.stubGlobal("fetch", fetchMock)
  return {
    fetchMock,
    requests,
    requestsTo: (urlMatch: string | RegExp) =>
      requests.filter((r) =>
        typeof urlMatch === "string" ? r.url === urlMatch : urlMatch.test(r.url)
      ),
  }
}

/** Account routes answered by the auth stub. */
export interface AuthStubConfig {
  account: import("@/domains/auth/model/types").UserAccount
  accessToken?: string
  refreshStatus?: 200 | 401
}

function authAccessBody(config: AuthStubConfig): Record<string, unknown> {
  return {
    access_token: config.accessToken ?? "test-access-token-value",
    token_type: "bearer",
    expires_in: 900,
    refresh_expires_in: 604800,
  }
}

/**
 * Answer the account routes with explicit auth responses.
 *
 * Login and cookie refresh return the browser access projection without a
 * refresh credential. Cookie logout answers 204. `GET /users/me` returns the
 * configured account. Every other request reaches the fallback handler, or a
 * 404 when none is given.
 */
export function installAuthStub(config: AuthStubConfig, fallback?: FetchHandler): FetchStub {
  return installFetchStub((req) => {
    if (req.url === "/auth/jwt/login" && req.method === "POST") {
      return ok(authAccessBody(config))
    }
    if (req.url === "/auth/jwt/refresh" && req.method === "POST") {
      if (config.refreshStatus === 401) {
        return err(401, { detail: "invalid refresh credential" })
      }
      return ok(authAccessBody(config))
    }
    if (req.url === "/auth/jwt/refresh" && req.method === "DELETE") {
      return new Response(null, { status: 204 })
    }
    if (req.url === "/users/me" && req.method === "GET") {
      return ok(config.account)
    }
    if (fallback !== undefined) return fallback(req)
    return err(404, { detail: "unhandled test route" })
  })
}

/** A manually-resolved promise used to assert pessimistic (pending) UI states. */
export function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}
