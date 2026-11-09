/**
 * Shared HTTP transport for every backend call.
 *
 * One fetch path supplies the Authorization header, the JSON defaults, the
 * abort signal, and the normalized {@link ApiError} for the whole client. The
 * module imports no account model and no role, so the auth domain can use it
 * without a layer cycle.
 *
 * Three auth modes exist. `access` is the protected default: it attaches the
 * in-memory Bearer credential, renews an expired credential before the call,
 * and retries one rejected call once. `public` sends no credential. `cookie`
 * is reserved for the two browser refresh-route methods: it sends the browser
 * marker inside the tab-wide cookie lock and never reads a credential from the
 * body.
 */
import { ApiError, parseDetail, toApiError } from "@/shared/api/http"
import {
  CHANGED_SESSION_MESSAGE,
  accessTokenExpired,
  getAccessToken,
  refreshAccessToken,
  sessionGeneration,
  withCookieLock,
} from "@/shared/api/session"

/** Browser marker required on every browser auth request. */
export const BROWSER_CLIENT_HEADERS: Readonly<Record<string, string>> = {
  "X-Polyweb-Client": "browser",
}

/** Options of one shared-transport request. */
export interface ApiRequestOptions extends RequestInit {
  auth?: "access" | "public" | "cookie"
}

const OFF_ORIGIN_MESSAGE = "The configured API origin is not the page origin."

/**
 * Return the configured API base, or an empty string for same-origin paths.
 *
 * A configured base that names another origin is rejected before any credential
 * transfer, so an environment mistake cannot send a token to a foreign host.
 */
function apiBase(): string {
  const configured = import.meta.env.VITE_API_URL as string | undefined
  const base = configured?.trim() ?? ""
  if (!base) return ""
  const resolved = new URL(base, window.location.origin)
  if (resolved.origin !== window.location.origin) throw new ApiError(0, OFF_ORIGIN_MESSAGE, null)
  return base.replace(/\/+$/, "")
}

async function readBody(response: Response): Promise<unknown> {
  let text: string
  try {
    text = await response.text()
  } catch {
    return undefined
  }
  if (!text) return undefined
  try {
    return JSON.parse(text) as unknown
  } catch {
    return text
  }
}

/**
 * Return the wait hint of a limited response, or `null` for no valid hint.
 *
 * Only a positive whole-second `Retry-After` value produces a hint. The client
 * shows that hint and never retries a limited request by itself.
 */
function retryAfterHint(response: Response): string | null {
  if (response.status !== 429) return null
  const raw = response.headers.get("retry-after")?.trim()
  if (raw === undefined || !/^[0-9]+$/.test(raw)) return null
  const seconds = Number(raw)
  if (seconds <= 0) return null
  return `Try again in ${seconds} second${seconds === 1 ? "" : "s"}.`
}

/** Return the error detail of one failed response, with its wait hint. */
function failureDetail(response: Response, body: unknown): string {
  const detail = parseDetail(body)
  const hint = retryAfterHint(response)
  return hint === null ? detail : `${detail} ${hint}`
}

async function send<T>(path: string, init: RequestInit): Promise<T> {
  const url = `${apiBase()}${path}`
  try {
    const response = await fetch(url, init)
    const body = await readBody(response)
    if (!response.ok) throw new ApiError(response.status, failureDetail(response, body), body)
    return body as T
  } catch (error) {
    throw toApiError(error)
  }
}

function prepareInit(init: RequestInit): RequestInit {
  const headers = new Headers(init.headers)
  if (init.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json")
  }
  return { ...init, headers, credentials: "same-origin" }
}

function withAuthorization(init: RequestInit, token: string | null): RequestInit {
  if (token === null) return init
  const headers = new Headers(init.headers)
  headers.set("Authorization", `Bearer ${token}`)
  return { ...init, headers }
}

function withBrowserMarker(init: RequestInit): RequestInit {
  const headers = new Headers(init.headers)
  for (const [name, value] of Object.entries(BROWSER_CLIENT_HEADERS)) headers.set(name, value)
  return { ...init, headers }
}

/** Return whether a protected call must renew access before it starts. */
function needsRenewal(): boolean {
  return getAccessToken() !== null && accessTokenExpired()
}

/** Retry one rejected protected call once, after a renewal when one is needed. */
async function retryUnauthorized<T>(
  path: string,
  init: RequestInit,
  presented: string | null,
  rejected: ApiError
): Promise<T> {
  const current = getAccessToken()
  if (current === null) throw rejected
  if (current === presented) await refreshAccessToken()
  return send<T>(path, withAuthorization(init, getAccessToken()))
}

async function accessRequest<T>(path: string, init: RequestInit): Promise<T> {
  if (needsRenewal()) await refreshAccessToken()
  const presented = getAccessToken()
  try {
    return await send<T>(path, withAuthorization(init, presented))
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 401) throw error
    return retryUnauthorized<T>(path, init, presented, error)
  }
}

async function cookieRequest<T>(path: string, init: RequestInit): Promise<T> {
  const startedGeneration = sessionGeneration()
  return withCookieLock(async () => {
    if (sessionGeneration() !== startedGeneration) {
      throw new ApiError(401, CHANGED_SESSION_MESSAGE, null)
    }
    const request = withAuthorization(withBrowserMarker(init), getAccessToken())
    return send<T>(path, request)
  })
}

/**
 * Perform one JSON API request through the shared transport.
 *
 * The default `access` mode serves every protected method of the API service.
 */
export async function requestJson<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const { auth = "access", ...init } = options
  const prepared = prepareInit(init)
  if (auth === "public") return send<T>(path, prepared)
  if (auth === "cookie") return cookieRequest<T>(path, prepared)
  return accessRequest<T>(path, prepared)
}
