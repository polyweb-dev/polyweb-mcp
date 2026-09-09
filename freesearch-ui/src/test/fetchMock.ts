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

function parseJsonBody(bodyText: string | undefined): unknown {
  if (bodyText === undefined) return undefined
  try {
    return JSON.parse(bodyText)
  } catch {
    return bodyText
  }
}

function headersToRecord(raw: RequestInit["headers"]): Record<string, string> {
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

function extractUrlAndMethod(
  input: unknown,
  init?: RequestInit
): { url: string; method: string } {
  return {
    url: typeof input === "string" ? input : String(input),
    method: (init?.method ?? "GET").toUpperCase(),
  }
}

function toRecordedRequest(input: unknown, init?: RequestInit): RecordedRequest {
  const { url, method } = extractUrlAndMethod(input, init)
  const bodyText = typeof init?.body === "string" ? init.body : undefined
  return {
    url,
    method,
    headers: headersToRecord(init?.headers),
    bodyText,
    body: parseJsonBody(bodyText),
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
