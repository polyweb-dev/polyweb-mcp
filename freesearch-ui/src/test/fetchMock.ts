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

function toRecordedRequest(input: unknown, init?: RequestInit): RecordedRequest {
  const url = typeof input === "string" ? input : String(input)
  const bodyText = typeof init?.body === "string" ? init.body : undefined
  let body: unknown
  if (bodyText !== undefined) {
    try {
      body = JSON.parse(bodyText)
    } catch {
      body = bodyText
    }
  }
  const headers: Record<string, string> = {}
  const raw = init?.headers
  if (raw instanceof Headers) {
    raw.forEach((value, key) => {
      headers[key] = value
    })
  } else if (Array.isArray(raw)) {
    for (const [key, value] of raw) headers[key] = value
  } else if (raw) {
    Object.assign(headers, raw)
  }
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
