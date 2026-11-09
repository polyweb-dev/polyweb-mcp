import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { deferred, err, installFetchStub, ok } from "@/test/fetchMock"
import {
  installFakeChannel,
  installImmediateLocks,
  removeLocks,
} from "@/test/browserStubs"
import {
  RENEWED_ACCESS_TOKEN,
  accessResponseFixture,
  adminAccountFixture,
  agentAccountFixture,
} from "@/test/authFixtures"

const CREDENTIALS = { email: "ada@example.com", password: "s3cret-pw" }
const INVALID_RESPONSE = "The server returned an unexpected account response."
const REFRESH_LEAK = "The server returned a refresh credential to the browser."

async function loadAuth() {
  const session = await import("@/shared/api/session")
  const authApi = await import("@/domains/auth/api/authApi")
  session.setAccessToken(null)
  return { session, authApi }
}

function installLocks(): void {
  installImmediateLocks()
  installFakeChannel()
}

beforeEach(() => {
  vi.resetModules()
  vi.unstubAllGlobals()
  removeLocks()
})

afterEach(() => {
  vi.unstubAllGlobals()
  removeLocks()
})

describe("login", () => {
  it("posts the OAuth2 form with the browser marker and installs the token", async () => {
    const { authApi, session } = await loadAuth()
    installLocks()
    const access = accessResponseFixture()
    const stub = installFetchStub(() => ok(access))

    const result = await authApi.login(CREDENTIALS)

    expect(result).toEqual(access)
    expect(stub.requests).toHaveLength(1)
    expect(stub.requests[0]).toMatchObject({
      url: "/auth/jwt/login",
      method: "POST",
    })
    expect(stub.requests[0]?.headers["content-type"]).toContain(
      "application/x-www-form-urlencoded"
    )
    expect(stub.requests[0]?.headers["x-polyweb-client"]).toBe("browser")
    const init = stub.fetchMock.mock.calls[0]?.[1] as RequestInit | undefined
    const body = init?.body
    if (!(body instanceof URLSearchParams)) {
      throw new Error("expected the login body to be an OAuth2 form")
    }
    expect(body.get("username")).toBe("ada@example.com")
    expect(body.get("password")).toBe("s3cret-pw")
    expect(session.getAccessToken()).toBe(access.access_token)
  })

  it("rejects a login body that carries a refresh credential", async () => {
    const { authApi, session } = await loadAuth()
    installLocks()
    const access = accessResponseFixture()
    installFetchStub(() => ok({ ...access, refresh_token: "cookie-leak" }))

    await expect(authApi.login(CREDENTIALS)).rejects.toMatchObject({
      status: 0,
      detail: REFRESH_LEAK,
    })
    expect(session.getAccessToken()).toBeNull()
  })

  it("rejects a login body missing the access token", async () => {
    const { authApi, session } = await loadAuth()
    installLocks()
    installFetchStub(() =>
      ok({ token_type: "bearer", expires_in: 900, refresh_expires_in: 604800 })
    )

    await expect(authApi.login(CREDENTIALS)).rejects.toMatchObject({
      status: 0,
      detail: INVALID_RESPONSE,
    })
    expect(session.getAccessToken()).toBeNull()
  })

  it("rejects a login body with the wrong token type", async () => {
    const { authApi, session } = await loadAuth()
    installLocks()
    installFetchStub(() => ok({ ...accessResponseFixture(), token_type: "mac" }))

    await expect(authApi.login(CREDENTIALS)).rejects.toMatchObject({
      status: 0,
      detail: INVALID_RESPONSE,
    })
    expect(session.getAccessToken()).toBeNull()
  })

  it("rejects login without the cookie lock primitives and sends no fetch", async () => {
    const { authApi, session } = await loadAuth()
    const stub = installFetchStub(() => ok(accessResponseFixture()))

    await expect(authApi.login(CREDENTIALS)).rejects.toMatchObject({
      status: 0,
      detail: session.UNSUPPORTED_SESSION_MESSAGE,
    })
    expect(stub.requests).toHaveLength(0)
    expect(session.getAccessToken()).toBeNull()
  })
})

describe("registerAccount", () => {
  it("posts exactly the email and the password to /auth/register in public mode", async () => {
    const { authApi } = await loadAuth()
    const account = adminAccountFixture()
    const stub = installFetchStub(() => ok(account))

    const result = await authApi.registerAccount({ ...CREDENTIALS })

    expect(result).toEqual(account)
    expect(stub.requests).toHaveLength(1)
    expect(stub.requests[0]).toMatchObject({
      url: "/auth/register",
      method: "POST",
    })
    expect(stub.requests[0]?.headers["content-type"]).toContain("application/json")
    expect(stub.requests[0]?.headers["authorization"]).toBeUndefined()
    expect(stub.requests[0]?.headers["x-polyweb-client"]).toBeUndefined()
    expect(stub.requests[0]?.body).toEqual({ ...CREDENTIALS })
    expect(Object.keys(stub.requests[0]?.body as object).sort()).toEqual(["email", "password"])
  })

  it("never sends a role or account-type field, whatever the caller passes", async () => {
    const { authApi } = await loadAuth()
    const stub = installFetchStub(() => ok(agentAccountFixture()))
    const smuggled = { ...CREDENTIALS, role: "admin", account_type: "installation" }

    await authApi.registerAccount(smuggled)

    expect(stub.requests[0]?.body).toEqual({ ...CREDENTIALS })
    expect(stub.requests.every((req) => req.headers["authorization"] === undefined)).toBe(true)
  })

  it("rejects an account body without the verification flag", async () => {
    const { authApi } = await loadAuth()
    const partial: Record<string, unknown> = { ...adminAccountFixture() }
    delete partial.is_verified
    installFetchStub(() => ok(partial))

    await expect(authApi.registerAccount({ ...CREDENTIALS })).rejects.toMatchObject({
      status: 0,
      detail: INVALID_RESPONSE,
    })
  })
})

describe("refreshAccess", () => {
  it("posts the cookie refresh with the browser marker and installs the token", async () => {
    const { authApi, session } = await loadAuth()
    installLocks()
    const renewed = accessResponseFixture({ access_token: RENEWED_ACCESS_TOKEN })
    const stub = installFetchStub(() => ok(renewed))

    const result = await authApi.refreshAccess()

    expect(result).toEqual(renewed)
    expect(stub.requests).toHaveLength(1)
    expect(stub.requests[0]).toMatchObject({
      url: "/auth/jwt/refresh",
      method: "POST",
    })
    expect(stub.requests[0]?.headers["x-polyweb-client"]).toBe("browser")
    expect(session.getAccessToken()).toBe(RENEWED_ACCESS_TOKEN)
  })

  it("installs no credential when the session ends before the refresh resolves", async () => {
    const { authApi, session } = await loadAuth()
    installLocks()
    const gate = deferred<Response>()
    const renewed = accessResponseFixture({ access_token: RENEWED_ACCESS_TOKEN })
    installFetchStub(() => gate.promise)

    const pending = authApi.refreshAccess()
    session.endLocalSession()
    gate.resolve(ok(renewed))
    const result = await pending

    expect(result).toEqual(renewed)
    expect(session.getAccessToken()).toBeNull()
  })

  it("rejects a refresh body that holds a refresh credential", async () => {
    const { authApi, session } = await loadAuth()
    installLocks()
    installFetchStub(() =>
      ok({ ...accessResponseFixture(), refresh_token: "cookie-leak" })
    )

    await expect(authApi.refreshAccess()).rejects.toMatchObject({
      status: 0,
      detail: REFRESH_LEAK,
    })
    expect(session.getAccessToken()).toBeNull()
  })

  it("rejects a refresh body missing the refresh lifetime", async () => {
    const { authApi, session } = await loadAuth()
    installLocks()
    installFetchStub(() =>
      ok({ access_token: "token-x", token_type: "bearer", expires_in: 900 })
    )

    await expect(authApi.refreshAccess()).rejects.toMatchObject({
      status: 0,
      detail: INVALID_RESPONSE,
    })
    expect(session.getAccessToken()).toBeNull()
  })
})

describe("logout", () => {
  it("deletes the refresh cookie and clears the token", async () => {
    const { authApi, session } = await loadAuth()
    installLocks()
    session.setAccessToken("live-token", 900)
    const stub = installFetchStub((req) => {
      if (req.url === "/auth/jwt/refresh" && req.method === "DELETE") {
        return new Response(null, { status: 204 })
      }
      return err(404, { detail: "unhandled test route" })
    })

    await expect(authApi.logout()).resolves.toBeUndefined()

    expect(stub.requests).toHaveLength(1)
    expect(stub.requests[0]).toMatchObject({
      url: "/auth/jwt/refresh",
      method: "DELETE",
    })
    expect(stub.requests[0]?.headers["x-polyweb-client"]).toBe("browser")
    expect(stub.requests[0]?.headers["authorization"]).toBe("Bearer live-token")
    expect(session.getAccessToken()).toBeNull()
  })

  it("tolerates HTTP 401 and still clears the token", async () => {
    const { authApi, session } = await loadAuth()
    installLocks()
    session.setAccessToken("live-token", 900)
    const stub = installFetchStub((req) => {
      if (req.url === "/auth/jwt/refresh" && req.method === "DELETE") {
        return err(401, { detail: "refresh family already revoked" })
      }
      return err(404, { detail: "unhandled test route" })
    })

    await expect(authApi.logout()).resolves.toBeUndefined()

    expect(stub.requests).toHaveLength(1)
    expect(session.getAccessToken()).toBeNull()
  })

  it("rethrows a server error but still clears the token", async () => {
    const { authApi, session } = await loadAuth()
    installLocks()
    session.setAccessToken("live-token", 900)
    installFetchStub((req) => {
      if (req.url === "/auth/jwt/refresh" && req.method === "DELETE") {
        return err(500, { detail: "logout failed" })
      }
      return err(404, { detail: "unhandled test route" })
    })

    await expect(authApi.logout()).rejects.toMatchObject({
      status: 500,
      detail: "logout failed",
    })
    expect(session.getAccessToken()).toBeNull()
  })

  it("rethrows a network failure but still clears the token", async () => {
    const { authApi, session } = await loadAuth()
    installLocks()
    session.setAccessToken("live-token", 900)
    installFetchStub(() => {
      throw new TypeError("network down")
    })

    await expect(authApi.logout()).rejects.toMatchObject({ status: 0 })
    expect(session.getAccessToken()).toBeNull()
  })
})

describe("getMe", () => {
  it("returns the account from GET /users/me", async () => {
    const { authApi } = await loadAuth()
    const account = adminAccountFixture()
    const stub = installFetchStub((req) => {
      if (req.url === "/users/me" && req.method === "GET") return ok(account)
      return err(404, { detail: "unhandled test route" })
    })

    const result = await authApi.getMe()

    expect(result).toEqual(account)
    expect(stub.requests).toHaveLength(1)
    expect(stub.requests[0]).toMatchObject({ url: "/users/me", method: "GET" })
    expect(stub.requests[0]?.headers["authorization"]).toBeUndefined()
  })

  it("decodes the backend account shape without a role and keeps the profile", async () => {
    const { authApi } = await loadAuth()
    const wire = {
      id: "44444444-4444-4444-8444-444444444444",
      email: "ada@example.com",
      auth_provider: "workos",
      auth_provider_id: "user_01",
      username: "ada",
      first_name: "Ada",
      last_name: "Lovelace",
      is_active: true,
      is_verified: false,
    }
    installFetchStub(() => ok(wire))

    const result = await authApi.getMe()

    expect(result).toEqual(wire)
    expect("role" in result).toBe(false)
  })

  it("reads absent profile fields as null and ignores unknown fields", async () => {
    const { authApi } = await loadAuth()
    installFetchStub(() =>
      ok({ id: "a1", email: "a@example.com", is_active: true, is_verified: true, role: "admin" })
    )

    const result = await authApi.getMe()

    expect(result).toEqual({
      id: "a1",
      email: "a@example.com",
      auth_provider: "local",
      auth_provider_id: null,
      username: null,
      first_name: null,
      last_name: null,
      is_active: true,
      is_verified: true,
    })
  })

  it("rejects a profile field of the wrong type", async () => {
    const { authApi } = await loadAuth()
    installFetchStub(() => ok({ ...adminAccountFixture(), username: 42 }))

    await expect(authApi.getMe()).rejects.toMatchObject({ status: 0, detail: INVALID_RESPONSE })
  })

  it("rejects a non-object account body", async () => {
    const { authApi } = await loadAuth()
    installFetchStub(() => ok([adminAccountFixture()]))

    await expect(authApi.getMe()).rejects.toMatchObject({
      status: 0,
      detail: INVALID_RESPONSE,
    })
  })
})

describe("T2-DENY-EDIT removed wrappers", () => {
  it("exposes no account lookup or role-change wrapper", async () => {
    const { authApi } = await loadAuth()

    expect("getAccount" in authApi).toBe(false)
    expect("changeRole" in authApi).toBe(false)
  })
})
