/**
 * Auth domain API: the account routes of the backend.
 *
 * Every call goes through the shared transport, so the Authorization header,
 * the abort behavior, and the error normalization stay in one place. A login and
 * a registration are public requests. A browser login and a cookie refresh send
 * the browser marker and keep the refresh credential inside its cookie. Every
 * success body is validated as unknown data before the UI uses it, and a body
 * that carries a refresh credential is rejected.
 */
import { BROWSER_CLIENT_HEADERS, requestJson } from "@/shared/api/client"
import { ApiError } from "@/shared/api/http"
import {
  beginLocalSession,
  endLocalSession,
  publishSessionChange,
  sessionGeneration,
  setAccessToken,
  withCookieLock,
} from "@/shared/api/session"
import type {
  AuthCredentials,
  AuthProviderKind,
  BrowserAccessResponse,
  RegistrationCredentials,
  UserAccount,
} from "../model/types"

const LOGIN_PATH = "/auth/jwt/login"
const REGISTER_PATH = "/auth/register"
const REFRESH_PATH = "/auth/jwt/refresh"
const ME_PATH = "/users/me"

const FORM_CONTENT_TYPE = { "Content-Type": "application/x-www-form-urlencoded" }

const INVALID_RESPONSE = "The server returned an unexpected account response."
const REFRESH_LEAK = "The server returned a refresh credential to the browser."

function invalidResponse(): ApiError {
  return new ApiError(0, INVALID_RESPONSE, null)
}

function isUnauthorized(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401
}

/**
 * Install one access credential only while the session generation still holds.
 *
 * A logout, a remote session change, or a new login raises the generation, so a
 * slow response of the old session installs no late credential.
 */
function installAccess(access: BrowserAccessResponse, startedAt: number): boolean {
  if (sessionGeneration() !== startedAt) return false
  setAccessToken(access.access_token, access.expires_in)
  return true
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

/** Decode the browser access projection and reject any refresh credential. */
function decodeAccessResponse(value: unknown): BrowserAccessResponse {
  const record = asRecord(value)
  if (record === null) throw invalidResponse()
  if ("refresh_token" in record) throw new ApiError(0, REFRESH_LEAK, null)
  const accessToken = record.access_token
  const expiresIn = record.expires_in
  const refreshExpiresIn = record.refresh_expires_in
  if (typeof accessToken !== "string" || !accessToken) throw invalidResponse()
  if (record.token_type !== "bearer") throw invalidResponse()
  if (typeof expiresIn !== "number" || typeof refreshExpiresIn !== "number") throw invalidResponse()
  return {
    access_token: accessToken,
    token_type: "bearer",
    expires_in: expiresIn,
    refresh_expires_in: refreshExpiresIn,
  }
}

/** Decode one optional profile text: absent and `null` read as `null`. */
function optionalText(value: unknown): string | null | undefined {
  if (value === undefined || value === null) return null
  return typeof value === "string" ? value : undefined
}

function decodeProvider(value: unknown): AuthProviderKind | null {
  if (value === undefined) return "local"
  return value === "local" || value === "workos" ? value : null
}

type AccountProfile = Pick<
  UserAccount,
  "auth_provider_id" | "username" | "first_name" | "last_name"
>

/** Decode the optional profile fields, or `null` when one has the wrong type. */
function decodeProfile(record: Record<string, unknown>): AccountProfile | null {
  const providerId = optionalText(record.auth_provider_id)
  const username = optionalText(record.username)
  const firstName = optionalText(record.first_name)
  const lastName = optionalText(record.last_name)
  if (
    providerId === undefined ||
    username === undefined ||
    firstName === undefined ||
    lastName === undefined
  ) {
    return null
  }
  return { auth_provider_id: providerId, username, first_name: firstName, last_name: lastName }
}

/**
 * Decode one safe account projection.
 *
 * The account carries no role: the shell reads authority from the live access
 * descriptors instead. Unknown extra fields are ignored and never copied.
 */
function decodeAccount(value: unknown): UserAccount {
  const record = asRecord(value)
  if (record === null) throw invalidResponse()
  const { id, email, is_active: isActive, is_verified: isVerified } = record
  if (typeof id !== "string" || !id || typeof email !== "string" || !email) throw invalidResponse()
  if (typeof isActive !== "boolean" || typeof isVerified !== "boolean") throw invalidResponse()
  const provider = decodeProvider(record.auth_provider)
  const profile = decodeProfile(record)
  if (provider === null || profile === null) throw invalidResponse()
  return {
    id,
    email,
    auth_provider: provider,
    ...profile,
    is_active: isActive,
    is_verified: isVerified,
  }
}

/**
 * Authenticate the browser and keep the access credential in memory only.
 *
 * The login runs inside the cookie lock, because its response installs the
 * refresh cookie. A programmatic client keeps the JSON pair on the same route.
 * A successful login starts a new session generation, so a response of the
 * previous session can never install its credential afterwards.
 */
export async function login(credentials: AuthCredentials): Promise<BrowserAccessResponse> {
  const startedAt = sessionGeneration()
  const form = new URLSearchParams({
    username: credentials.email,
    password: credentials.password,
  })
  const body = await withCookieLock(() =>
    requestJson<unknown>(LOGIN_PATH, {
      auth: "public",
      method: "POST",
      headers: { ...FORM_CONTENT_TYPE, ...BROWSER_CLIENT_HEADERS },
      body: form,
    })
  )
  const access = decodeAccessResponse(body)
  if (installAccess(access, startedAt)) {
    beginLocalSession()
    publishSessionChange()
  }
  return access
}

/**
 * Create one account on the public route. The route returns no credential.
 *
 * The body holds the email and the password only: the backend rejects any
 * role or account-type field, and authority comes from explicit assignments.
 */
export async function registerAccount(input: RegistrationCredentials): Promise<UserAccount> {
  const body = await requestJson<unknown>(REGISTER_PATH, {
    auth: "public",
    method: "POST",
    body: JSON.stringify({ email: input.email, password: input.password }),
  })
  return decodeAccount(body)
}

/** Rotate the refresh cookie into one access credential. */
export async function refreshAccess(): Promise<BrowserAccessResponse> {
  const startedAt = sessionGeneration()
  const body = await requestJson<unknown>(REFRESH_PATH, { auth: "cookie", method: "POST" })
  const access = decodeAccessResponse(body)
  installAccess(access, startedAt)
  return access
}

/**
 * End the browser session, then drop the local credential in every case.
 *
 * An HTTP 401 means the family is already revoked, which is the intended end
 * state, so it does not become an error for the caller.
 */
export async function logout(): Promise<void> {
  try {
    await withCookieLock(() =>
      requestJson<unknown>(REFRESH_PATH, { auth: "cookie", method: "DELETE" })
    )
  } catch (error) {
    if (!isUnauthorized(error)) throw error
  } finally {
    // The local session end raises the generation and tells this tab and every
    // other tab, so no queued task can install a credential of this session.
    endLocalSession()
  }
}

/** Return the authenticated account. */
export async function getMe(): Promise<UserAccount> {
  return decodeAccount(await requestJson<unknown>(ME_PATH))
}
