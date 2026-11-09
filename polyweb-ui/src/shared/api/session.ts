/**
 * Memory-only session store and native tab coordination for the auth transport.
 *
 * The access credential and its deadline live in module memory only. Nothing in
 * this module writes the credential to Redux, redux-persist, storage, a URL, or
 * browser history, and the refresh credential never leaves its HttpOnly cookie.
 *
 * The store owns no account model: the auth domain installs the cookie policy
 * through {@link configureAuthTransport}. One refresh promise serves every
 * caller in this tab. The Web Locks API serializes cookie rotation across tabs
 * of the same origin, and a BroadcastChannel carries session-change hints only —
 * never a token, a password, or an account payload.
 */
import { ApiError } from "@/shared/api/http"

/** The cookie policy the auth domain installs into the memory store. */
export interface AuthTransportHandlers {
  /** Perform one cookie refresh and publish the new access credential. */
  refresh: () => Promise<unknown>
  /** Drop leftover protected state after the session ended. */
  invalidate: () => void
}

/** Reason shown when the browser lacks Web Locks or BroadcastChannel. */
export const UNSUPPORTED_SESSION_MESSAGE =
  "This browser cannot keep a secure account session. Use a current browser."

/** Reason shown when a queued operation lost its session generation. */
export const CHANGED_SESSION_MESSAGE = "The account session changed. Sign in again."

/** One exclusive lock serializes cookie rotation across the same origin. */
const COOKIE_LOCK_NAME = "polyweb:auth-cookie"
const SESSION_CHANNEL_NAME = "polyweb:session"
const SESSION_EVENT = "session-change"

/**
 * Fail-closed policy for a transport without an auth domain: a refresh attempt
 * ends the session instead of sending a cookie request that no module can read.
 */
const NO_POLICY: AuthTransportHandlers = {
  refresh: () => Promise.reject(changedSessionError()),
  invalidate: () => {},
}

let accessToken: string | null = null
let accessDeadline = 0
let refreshPromise: Promise<void> | null = null
let policy: AuthTransportHandlers = NO_POLICY
let generation = 0
let channel: BroadcastChannel | null = null
let lockDepth = 0
let notifying = false
let moduleListenerInstalled = false
const listeners = new Set<() => void>()

function changedSessionError(): ApiError {
  return new ApiError(401, CHANGED_SESSION_MESSAGE, null)
}

function unsupportedSessionError(): ApiError {
  return new ApiError(0, UNSUPPORTED_SESSION_MESSAGE, null)
}

/** Return the in-memory access credential, or `null` when none exists. */
export function getAccessToken(): string | null {
  return accessToken
}

/** Replace the in-memory access credential and start its deadline. */
export function setAccessToken(token: string | null, expiresIn?: number): void {
  accessToken = token
  accessDeadline = token !== null && expiresIn !== undefined ? Date.now() + expiresIn * 1000 : 0
}

/** Return whether the access credential is absent or past its deadline. */
export function accessTokenExpired(): boolean {
  return accessToken === null || Date.now() >= accessDeadline
}

/** Return the session generation. Every login, logout, or switch changes it. */
export function sessionGeneration(): number {
  return generation
}

/**
 * Start a new session in this tab and raise the generation.
 *
 * Every queued auth task of the previous session then fails its generation
 * check, so a late response cannot install a credential of the old session.
 * The caller owns the new credential.
 */
export function beginLocalSession(): void {
  generation += 1
}

/** Return whether this browser can hold a cookie session at all. */
export function cookieTransportSupported(): boolean {
  if (typeof BroadcastChannel !== "function") return false
  if (typeof navigator === "undefined") return false
  return typeof navigator.locks?.request === "function"
}

/**
 * Install the cookie policy of the auth domain and return a disposer.
 *
 * The disposer clears the policy only while it is still the installed one, so a
 * late unmount cannot remove a newer policy.
 */
export function configureAuthTransport(next: AuthTransportHandlers): () => void {
  policy = next
  return () => {
    if (policy === next) policy = NO_POLICY
  }
}

function notifyListeners(): void {
  // A listener can publish again, so the pass is neither nested nor repeated.
  if (notifying) return
  notifying = true
  try {
    for (const listener of [...listeners]) listener()
  } finally {
    notifying = false
  }
}

/**
 * Forget the session in this tab: drop the access credential, dispose protected
 * state, and invalidate every queued auth task through the generation check.
 *
 * The generation rises once per session end. This function never notifies the
 * listeners itself, so a listener cannot trigger a second rise.
 */
function forgetSession(): void {
  generation += 1
  setAccessToken(null)
  policy.invalidate()
}

/** Forget a session that another tab ended, then tell the local listeners. */
function handleRemoteSessionChange(): void {
  forgetSession()
  notifyListeners()
}

/**
 * End the local session: forget the credential, tell the local listeners, then
 * tell the other tabs.
 *
 * The generation rises here, so every queued auth task of this session fails
 * its generation check and installs no late credential.
 */
export function endLocalSession(): void {
  forgetSession()
  notifyListeners()
  publishSessionChange()
}

function sessionChannel(): BroadcastChannel | null {
  if (typeof BroadcastChannel !== "function") return null
  if (channel === null) {
    channel = new BroadcastChannel(SESSION_CHANNEL_NAME)
    channel.onmessage = () => notifyListeners()
  }
  return channel
}

/**
 * Install this module's own listener, which forgets a session that another tab
 * ended or replaced. It uses the public subscription path, so the module and the
 * UI observe the same events.
 */
function watchRemoteSessionChanges(): void {
  if (moduleListenerInstalled) return
  moduleListenerInstalled = true
  subscribeSessionChanges(handleRemoteSessionChange)
}

/**
 * Subscribe to session changes from this tab and from other tabs.
 *
 * Only the change hint crosses the channel. The callback receives no token and
 * no account payload, so it must reload the session from the server.
 */
export function subscribeSessionChanges(onChange: () => void): () => void {
  watchRemoteSessionChanges()
  sessionChannel()
  listeners.add(onChange)
  return () => {
    listeners.delete(onChange)
  }
}

/** Publish one session-change hint to every other tab of this origin. */
export function publishSessionChange(): void {
  sessionChannel()?.postMessage({ type: SESSION_EVENT })
}

/**
 * Run one cookie task under the tab-wide auth lock.
 *
 * The lock is never acquired twice in this tab: a nested task reuses the held
 * lock. The browser selects its current cookie only when the request starts
 * inside the lock, so a queued rotation cannot answer with a stale cookie.
 */
export async function withCookieLock<T>(task: () => Promise<T>): Promise<T> {
  if (!cookieTransportSupported()) throw unsupportedSessionError()
  watchRemoteSessionChanges()
  if (lockDepth > 0) return task()
  return navigator.locks.request(COOKIE_LOCK_NAME, async () => {
    lockDepth += 1
    try {
      return await task()
    } finally {
      lockDepth -= 1
    }
  })
}

async function refreshThroughPolicy(): Promise<void> {
  try {
    await policy.refresh()
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) endLocalSession()
    throw error
  }
}

/**
 * Supply one cookie refresh promise to every caller within this tab.
 *
 * The lock grant is checked against the captured generation, so a refresh that
 * another tab obsoleted never installs a late credential.
 */
export function refreshAccessToken(): Promise<void> {
  if (refreshPromise === null) {
    const startedAt = generation
    refreshPromise = withCookieLock(async () => {
      if (generation !== startedAt) throw changedSessionError()
      await refreshThroughPolicy()
    }).finally(() => {
      refreshPromise = null
    })
  }
  return refreshPromise
}

// Install the fail-closed default policy, so an early refresh attempt ends the
// session instead of reaching a cookie route that no module can read.
configureAuthTransport(NO_POLICY)
