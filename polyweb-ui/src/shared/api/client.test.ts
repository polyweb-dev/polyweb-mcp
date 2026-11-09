import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { ApiError } from "@/shared/api/http"
import { installFetchStub, ok, err } from "@/test/fetchMock"

class FakeChannel {
  static instances: FakeChannel[] = []
  onmessage: ((event: unknown) => void) | null = null
  posted: unknown[] = []
  readonly name: string
  constructor(name: string) {
    this.name = name
    FakeChannel.instances.push(this)
  }
  postMessage(message: unknown): void {
    this.posted.push(message)
  }
}

async function loadTransport() {
  const session = await import("@/shared/api/session")
  const client = await import("@/shared/api/client")
  return { session, client }
}

function installImmediateLocks() {
  const request = vi.fn(
    async (name: string, task: () => Promise<unknown>): Promise<unknown> => task()
  )
  Object.defineProperty(navigator, "locks", { value: { request }, configurable: true })
  return request
}

function installChannel() {
  FakeChannel.instances = []
  vi.stubGlobal("BroadcastChannel", FakeChannel as unknown as typeof BroadcastChannel)
}

function removeLocks(): void {
  if ("locks" in navigator) Reflect.deleteProperty(navigator, "locks")
}

function installPolicy(
  session: Awaited<ReturnType<typeof loadTransport>>["session"],
  token: string
) {
  const refresh = vi.fn(async (): Promise<void> => {
    session.setAccessToken(token, 900)
  })
  const invalidate = vi.fn()
  session.configureAuthTransport({ refresh, invalidate })
  return { refresh, invalidate }
}

beforeEach(() => {
  vi.resetModules()
  vi.unstubAllGlobals()
  removeLocks()
  FakeChannel.instances = []
  vi.stubEnv("VITE_API_URL", "")
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
  removeLocks()
  FakeChannel.instances = []
})

describe("request modes and body forms", () => {
  it("sends public requests without a credential and with JSON defaults", async () => {
    const { client, session } = await loadTransport()
    session.setAccessToken("memory-token", 900)
    const stub = installFetchStub(() => ok({ ok: true }))
    const body = { query: "hello" }

    const result = await client.requestJson<{ ok: boolean }>("/search", {
      auth: "public",
      method: "POST",
      body: JSON.stringify(body),
    })

    expect(result).toEqual({ ok: true })
    expect(stub.requests).toHaveLength(1)
    const [first] = stub.requests
    expect(first).toMatchObject({ url: "/search", method: "POST" })
    expect(first?.body).toEqual(body)
    expect(first?.headers["authorization"]).toBeUndefined()
    expect(first?.headers["content-type"]).toContain("application/json")
  })

  it("attaches the memory Bearer credential in access mode", async () => {
    const { client, session } = await loadTransport()
    session.setAccessToken("memory-token", 900)
    const stub = installFetchStub(() => ok({ ok: true }))

    await client.requestJson("/api/v1/providers")

    expect(stub.requests).toHaveLength(1)
    expect(stub.requests[0]?.headers["authorization"]).toBe("Bearer memory-token")
  })

  it("sends no Authorization when memory holds no token", async () => {
    const { client } = await loadTransport()
    const stub = installFetchStub(() => ok({ ok: true }))

    await client.requestJson("/api/v1/providers")

    expect(stub.requests).toHaveLength(1)
    expect(stub.requests[0]?.headers["authorization"]).toBeUndefined()
  })

  it("keeps an explicit form content type for OAuth2 login bodies", async () => {
    const { client } = await loadTransport()
    const stub = installFetchStub(() => ok({ ok: true }))
    const form = new URLSearchParams({ username: "a@example.com", password: "x" })

    await client.requestJson("/auth/jwt/login", {
      auth: "public",
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: form.toString(),
    })

    expect(stub.requests).toHaveLength(1)
    expect(stub.requests[0]?.headers["content-type"]).toContain(
      "application/x-www-form-urlencoded"
    )
  })

  it("sends no content type for a body-free GET", async () => {
    const { client } = await loadTransport()
    const stub = installFetchStub(() => ok({ ok: true }))

    await client.requestJson("/api/v1/providers")

    expect(stub.requests).toHaveLength(1)
    expect(stub.requests[0]?.headers["content-type"]).toBeUndefined()
  })

  it("forwards the caller abort signal to fetch", async () => {
    const { client } = await loadTransport()
    const stub = installFetchStub(() => ok({ ok: true }))
    const controller = new AbortController()

    await client.requestJson("/api/v1/providers", { signal: controller.signal })

    expect(stub.requests).toHaveLength(1)
    expect(stub.requests[0]?.signal).toBe(controller.signal)
  })

  it("sends credentials in same-origin mode", async () => {
    const { client, session } = await loadTransport()
    session.setAccessToken("memory-token", 900)
    const seen: RequestInit[] = []
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: unknown, init?: RequestInit) => {
        if (init !== undefined) seen.push(init)
        return new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      })
    )

    await client.requestJson("/search", { method: "POST", body: JSON.stringify({ q: 1 }) })

    expect(seen).toHaveLength(1)
    expect(seen[0]?.credentials).toBe("same-origin")
  })
})

describe("off-origin rejection", () => {
  it("rejects a foreign API origin before any credential transfer", async () => {
    const { client, session } = await loadTransport()
    session.setAccessToken("memory-token", 900)
    vi.stubEnv("VITE_API_URL", "https://evil.example.com")
    const fetchMock = vi.fn(async () => new Response("{}", { status: 200 }))
    vi.stubGlobal("fetch", fetchMock)

    const failure = await client
      .requestJson("/search", { method: "POST", body: JSON.stringify({ q: 1 }) })
      .then(
        () => null,
        (error: unknown) => error
      )
    const errors = await import("@/shared/api/http")

    expect(failure).toBeInstanceOf(errors.ApiError)
    expect((failure as ApiError).status).toBe(0)
    expect(fetchMock).not.toHaveBeenCalled()
  })
})

describe("access renewal and retry", () => {
  it("renews an expired token before the call", async () => {
    const { client, session } = await loadTransport()
    installImmediateLocks()
    installChannel()
    session.setAccessToken("token-old", 0)
    const { refresh } = installPolicy(session, "token-new")
    const stub = installFetchStub(() => ok({ ok: true }))

    await client.requestJson("/api/v1/providers")

    expect(refresh).toHaveBeenCalledTimes(1)
    expect(stub.requests).toHaveLength(1)
    expect(stub.requests[0]?.headers["authorization"]).toBe("Bearer token-new")
  })

  it("retries one rejected call once after renewal", async () => {
    const { client, session } = await loadTransport()
    installImmediateLocks()
    installChannel()
    session.setAccessToken("token-old", 900)
    const { refresh } = installPolicy(session, "token-new")
    const stub = installFetchStub((req) =>
      req.headers["authorization"] === "Bearer token-old"
        ? err(401, { detail: "not authenticated" })
        : ok({ ok: true })
    )

    const result = await client.requestJson<{ ok: boolean }>("/api/v1/providers")

    expect(result).toEqual({ ok: true })
    expect(refresh).toHaveBeenCalledTimes(1)
    expect(stub.requests).toHaveLength(2)
    expect(stub.requests[0]?.headers["authorization"]).toBe("Bearer token-old")
    expect(stub.requests[1]?.headers["authorization"]).toBe("Bearer token-new")
  })

  it("throws after a second 401 without a further retry", async () => {
    const { client, session } = await loadTransport()
    installImmediateLocks()
    installChannel()
    session.setAccessToken("token-old", 900)
    const { refresh } = installPolicy(session, "token-new")
    const stub = installFetchStub(() => err(401, { detail: "not authenticated" }))

    await expect(client.requestJson("/api/v1/providers")).rejects.toMatchObject({
      status: 401,
    })

    expect(stub.requests).toHaveLength(2)
    expect(refresh).toHaveBeenCalledTimes(1)
  })

  it("shares one refresh across parallel rejected calls", async () => {
    const { client, session } = await loadTransport()
    installImmediateLocks()
    installChannel()
    session.setAccessToken("token-old", 900)
    const { refresh } = installPolicy(session, "token-new")
    const stub = installFetchStub((req) =>
      req.headers["authorization"] === "Bearer token-old"
        ? err(401, { detail: "not authenticated" })
        : ok({ ok: true })
    )

    const [first, second] = await Promise.all([
      client.requestJson<{ ok: boolean }>("/api/v1/providers"),
      client.requestJson<{ ok: boolean }>("/dashboard"),
    ])

    expect(first).toEqual({ ok: true })
    expect(second).toEqual({ ok: true })
    expect(refresh).toHaveBeenCalledTimes(1)
    expect(stub.requestsTo("/api/v1/providers")).toHaveLength(2)
    expect(stub.requestsTo("/dashboard")).toHaveLength(2)
  })

  it("never renews on 403 and never retries the rejected call", async () => {
    const { client, session } = await loadTransport()
    installImmediateLocks()
    installChannel()
    session.setAccessToken("token-old", 900)
    const { refresh } = installPolicy(session, "token-new")
    const stub = installFetchStub(() => err(403, { detail: "insufficient role" }))

    await expect(client.requestJson("/api/v1/providers")).rejects.toMatchObject({
      status: 403,
    })

    expect(stub.requests).toHaveLength(1)
    expect(refresh).not.toHaveBeenCalled()
  })

  it("never renews on 429", async () => {
    const { client, session } = await loadTransport()
    installImmediateLocks()
    installChannel()
    session.setAccessToken("token-old", 900)
    const { refresh } = installPolicy(session, "token-new")
    const stub = installFetchStub(() => err(429, { detail: "too many requests" }))

    await expect(client.requestJson("/api/v1/providers")).rejects.toMatchObject({
      status: 429,
    })

    expect(stub.requests).toHaveLength(1)
    expect(refresh).not.toHaveBeenCalled()
  })

  it("appends the wait hint on a 429 with a valid retry delay", async () => {
    const { client, session } = await loadTransport()
    installImmediateLocks()
    installChannel()
    session.setAccessToken("token-old", 900)
    installFetchStub(
      () =>
        new Response(JSON.stringify({ detail: "too many authentication attempts" }), {
          status: 429,
          headers: { "Content-Type": "application/json", "Retry-After": "30" },
        })
    )

    await expect(
      client.requestJson("/auth/jwt/login", {
        auth: "public",
        method: "POST",
        body: "username=a&password=b",
      })
    ).rejects.toMatchObject({
      status: 429,
      detail: "too many authentication attempts Try again in 30 seconds.",
    })
  })

  it("uses the singular wait hint for a one-second delay", async () => {
    const { client } = await loadTransport()
    installFetchStub(
      () =>
        new Response(JSON.stringify({ detail: "too many authentication attempts" }), {
          status: 429,
          headers: { "Content-Type": "application/json", "Retry-After": "1" },
        })
    )

    await expect(
      client.requestJson("/auth/jwt/login", { auth: "public", method: "POST" })
    ).rejects.toMatchObject({
      status: 429,
      detail: "too many authentication attempts Try again in 1 second.",
    })
  })

  it("shows no wait hint for a missing or invalid retry delay", async () => {
    const { client } = await loadTransport()
    for (const retryAfter of [null, "soon", "0", "-5", "1.5", ""]) {
      const headers: Record<string, string> = { "Content-Type": "application/json" }
      if (retryAfter !== null) headers["Retry-After"] = retryAfter
      installFetchStub(
        () =>
          new Response(JSON.stringify({ detail: "too many registration attempts" }), {
            status: 429,
            headers,
          })
      )

      await expect(
        client.requestJson("/auth/register", { auth: "public", method: "POST" })
      ).rejects.toMatchObject({
        status: 429,
        detail: "too many registration attempts",
      })
    }
  })

  it("shows no wait hint outside a 429 response", async () => {
    const { client } = await loadTransport()
    installFetchStub(
      () =>
        new Response(JSON.stringify({ detail: "invalid authentication request" }), {
          status: 400,
          headers: { "Content-Type": "application/json", "Retry-After": "30" },
        })
    )

    await expect(
      client.requestJson("/auth/register", { auth: "public", method: "POST" })
    ).rejects.toMatchObject({
      status: 400,
      detail: "invalid authentication request",
    })
  })

  it("never replays a request after a network failure", async () => {
    const { client, session } = await loadTransport()
    installImmediateLocks()
    installChannel()
    session.setAccessToken("token-old", 900)
    const { refresh } = installPolicy(session, "token-new")
    const fetchMock = vi.fn(async () => {
      throw new TypeError("network down")
    })
    vi.stubGlobal("fetch", fetchMock)

    await expect(client.requestJson("/api/v1/providers")).rejects.toMatchObject({
      status: 0,
    })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(refresh).not.toHaveBeenCalled()
  })
})

describe("cookie mode", () => {
  it("sends the browser marker with the current access inside the tab lock", async () => {
    const { client, session } = await loadTransport()
    const request = installImmediateLocks()
    installChannel()
    session.setAccessToken("token-current", 900)
    const stub = installFetchStub(() => ok({ ok: true }))

    await client.requestJson("/auth/jwt/refresh", { auth: "cookie", method: "POST" })

    expect(request).toHaveBeenCalledTimes(1)
    expect(request.mock.calls[0]?.[0]).toBe("polyweb:auth-cookie")
    expect(stub.requests).toHaveLength(1)
    expect(stub.requests[0]?.headers["x-polyweb-client"]).toBe("browser")
    expect(stub.requests[0]?.headers["authorization"]).toBe("Bearer token-current")
  })

  it("sends the marker without Authorization when memory holds no token", async () => {
    const { client } = await loadTransport()
    installImmediateLocks()
    installChannel()
    const stub = installFetchStub(() => ok({ ok: true }))

    await client.requestJson("/auth/jwt/refresh", { auth: "cookie", method: "POST" })

    expect(stub.requests).toHaveLength(1)
    expect(stub.requests[0]?.headers["x-polyweb-client"]).toBe("browser")
    expect(stub.requests[0]?.headers["authorization"]).toBeUndefined()
  })

  it("rejects a stale queued cookie task without a fetch", async () => {
    const { client, session } = await loadTransport()
    installChannel()
    session.setAccessToken("token-current", 900)
    let queued: (() => Promise<unknown>) | undefined
    const request = vi.fn(
      (name: string, task: () => Promise<unknown>): Promise<unknown> =>
        new Promise<unknown>((resolve, reject) => {
          queued = () => task().then(resolve, reject)
        })
    )
    Object.defineProperty(navigator, "locks", { value: { request }, configurable: true })
    const fetchMock = vi.fn(async () => ok({ ok: true }))
    vi.stubGlobal("fetch", fetchMock)
    const pending = client.requestJson("/auth/jwt/refresh", {
      auth: "cookie",
      method: "POST",
    })
    const assertion = expect(pending).rejects.toMatchObject({ status: 401 })
    expect(request).toHaveBeenCalledTimes(1)

    FakeChannel.instances[0]?.onmessage?.({ data: { type: "session-change" } })
    const task = queued
    expect(task).toBeDefined()
    if (task === undefined) throw new Error("cookie lock task never queued")
    await task()
    await assertion

    expect(fetchMock).not.toHaveBeenCalled()
  })
})
