import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"

const LOCK_NAME = "polyweb:auth-cookie"
const CHANNEL_NAME = "polyweb:session"

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

async function loadSession() {
  return import("@/shared/api/session")
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
  return FakeChannel
}

function removeLocks(): void {
  if ("locks" in navigator) Reflect.deleteProperty(navigator, "locks")
}

function moduleChannel(): FakeChannel | undefined {
  return FakeChannel.instances.find((entry) => entry.name === CHANNEL_NAME)
}

beforeEach(() => {
  vi.resetModules()
  vi.unstubAllGlobals()
  removeLocks()
  FakeChannel.instances = []
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
  removeLocks()
  FakeChannel.instances = []
})

describe("session memory state", () => {
  it("starts empty and reports expiry", async () => {
    const session = await loadSession()

    expect(session.getAccessToken()).toBeNull()
    expect(session.accessTokenExpired()).toBe(true)
    expect(session.sessionGeneration()).toBe(0)
  })

  it("holds a token with a lifetime until the deadline", async () => {
    const session = await loadSession()

    session.setAccessToken("token-a", 900)

    expect(session.getAccessToken()).toBe("token-a")
    expect(session.accessTokenExpired()).toBe(false)
  })

  it("treats a zero lifetime as expired", async () => {
    const session = await loadSession()

    session.setAccessToken("token-a", 0)

    expect(session.getAccessToken()).toBe("token-a")
    expect(session.accessTokenExpired()).toBe(true)
  })

  it("treats a token without an expiry as expired", async () => {
    const session = await loadSession()

    session.setAccessToken("token-a")

    expect(session.getAccessToken()).toBe("token-a")
    expect(session.accessTokenExpired()).toBe(true)
  })

  it("clears the token and reports expiry after logout", async () => {
    const session = await loadSession()
    session.setAccessToken("token-a", 900)

    session.setAccessToken(null)

    expect(session.getAccessToken()).toBeNull()
    expect(session.accessTokenExpired()).toBe(true)
  })
})

describe("single refresh promise", () => {
  it("shares one policy refresh across parallel callers", async () => {
    const session = await loadSession()
    installImmediateLocks()
    installChannel()
    const refresh = vi.fn(async (): Promise<void> => {
      session.setAccessToken("token-new", 900)
    })
    const invalidate = vi.fn()
    session.configureAuthTransport({ refresh, invalidate })

    const [first, second] = await Promise.all([
      session.refreshAccessToken(),
      session.refreshAccessToken(),
    ])

    expect(first).toBeUndefined()
    expect(second).toBeUndefined()
    expect(refresh).toHaveBeenCalledTimes(1)
    expect(session.getAccessToken()).toBe("token-new")
  })

  it("ends the session when the policy refresh fails with 401", async () => {
    const session = await loadSession()
    installImmediateLocks()
    installChannel()
    session.setAccessToken("token-old", 900)
    const before = session.sessionGeneration()
    const errors = await import("@/shared/api/http")
    const refresh = vi.fn(async (): Promise<void> => {
      throw new errors.ApiError(401, "invalid refresh credential", null)
    })
    session.configureAuthTransport({ refresh, invalidate: () => {} })

    await expect(session.refreshAccessToken()).rejects.toMatchObject({ status: 401 })

    expect(session.getAccessToken()).toBeNull()
    expect(session.sessionGeneration()).toBeGreaterThan(before)
  })

  it("rejects through the fail-closed default policy without a cookie request", async () => {
    const session = await loadSession()
    const request = installImmediateLocks()
    installChannel()
    session.setAccessToken("token-old", 900)

    await expect(session.refreshAccessToken()).rejects.toMatchObject({
      status: 401,
      detail: session.CHANGED_SESSION_MESSAGE,
    })

    expect(request).toHaveBeenCalledTimes(1)
    expect(session.getAccessToken()).toBeNull()
    expect(session.sessionGeneration()).toBeGreaterThan(0)
  })

  it("never installs a late credential after a generation change", async () => {
    const session = await loadSession()
    installChannel()
    let queued: (() => Promise<void>) | undefined
    const request = vi.fn(
      (name: string, task: () => Promise<void>): Promise<void> =>
        new Promise<void>((resolve, reject) => {
          queued = () => task().then(resolve, reject)
        })
    )
    Object.defineProperty(navigator, "locks", { value: { request }, configurable: true })
    const refresh = vi.fn(async (): Promise<void> => {
      session.setAccessToken("token-late", 900)
    })
    session.configureAuthTransport({ refresh, invalidate: () => {} })
    const pending = session.refreshAccessToken()
    const assertion = expect(pending).rejects.toMatchObject({
      status: 401,
      detail: session.CHANGED_SESSION_MESSAGE,
    })
    expect(request).toHaveBeenCalledTimes(1)

    moduleChannel()?.onmessage?.({ data: { type: "session-change" } })
    const task = queued
    expect(task).toBeDefined()
    if (task === undefined) throw new Error("cookie lock task never queued")
    await task()
    await assertion

    expect(refresh).not.toHaveBeenCalled()
    expect(session.getAccessToken()).toBeNull()
  })
})

describe("cookie lock order", () => {
  it("runs cookie tasks under the exact tab lock name", async () => {
    const session = await loadSession()
    const request = installImmediateLocks()
    installChannel()

    const result = await session.withCookieLock(async () => "cookie-ok")

    expect(result).toBe("cookie-ok")
    expect(request).toHaveBeenCalledTimes(1)
    expect(request.mock.calls[0]?.[0]).toBe(LOCK_NAME)
  })

  it("reuses the held lock instead of a nested acquisition", async () => {
    const session = await loadSession()
    const request = installImmediateLocks()
    installChannel()

    const result = await session.withCookieLock(async () =>
      session.withCookieLock(async () => "inner-ok")
    )

    expect(result).toBe("inner-ok")
    expect(request).toHaveBeenCalledTimes(1)
  })
})

describe("transport policy", () => {
  it("disposes only the installed policy", async () => {
    const session = await loadSession()
    installImmediateLocks()
    installChannel()
    const firstRefresh = vi.fn(async (): Promise<void> => {
      session.setAccessToken("token-first", 900)
    })
    const secondRefresh = vi.fn(async (): Promise<void> => {
      session.setAccessToken("token-second", 900)
    })
    const disposeFirst = session.configureAuthTransport({
      refresh: firstRefresh,
      invalidate: () => {},
    })
    session.configureAuthTransport({ refresh: secondRefresh, invalidate: () => {} })

    disposeFirst()
    await session.refreshAccessToken()

    expect(firstRefresh).not.toHaveBeenCalled()
    expect(secondRefresh).toHaveBeenCalledTimes(1)
    expect(session.getAccessToken()).toBe("token-second")
  })
})

describe("session channel hints", () => {
  it("publishes a token-free hint under the session channel name", async () => {
    const session = await loadSession()
    installImmediateLocks()
    installChannel()
    session.setAccessToken("token-secret-value", 900)

    session.publishSessionChange()

    const channel = moduleChannel()
    expect(channel?.posted).toHaveLength(1)
    expect(channel?.posted[0]).toEqual({ type: "session-change" })
    expect(JSON.stringify(channel?.posted[0])).not.toContain("token-secret-value")
  })

  it("clears memory when a remote hint arrives", async () => {
    const session = await loadSession()
    installImmediateLocks()
    installChannel()
    session.setAccessToken("token-old", 900)
    const seen: string[] = []
    const dispose = session.subscribeSessionChanges(() => {
      seen.push("changed")
    })
    const before = session.sessionGeneration()

    moduleChannel()?.onmessage?.({ data: { type: "session-change" } })

    expect(seen).toEqual(["changed"])
    expect(session.getAccessToken()).toBeNull()
    expect(session.sessionGeneration()).toBe(before + 1)
    dispose()
  })
})

describe("unsupported browsers", () => {
  it("reports no cookie transport without locks and channel", async () => {
    const session = await loadSession()
    vi.stubGlobal("BroadcastChannel", undefined as unknown as typeof BroadcastChannel)
    removeLocks()

    expect(session.cookieTransportSupported()).toBe(false)
  })

  it("reports support only when both primitives exist", async () => {
    const first = await loadSession()
    installChannel()
    removeLocks()

    expect(first.cookieTransportSupported()).toBe(false)
  })

  it("rejects cookie tasks with the compatibility error", async () => {
    const session = await loadSession()
    vi.stubGlobal("BroadcastChannel", undefined as unknown as typeof BroadcastChannel)
    removeLocks()
    const refresh = vi.fn()

    await expect(session.withCookieLock(async () => "never")).rejects.toMatchObject({
      status: 0,
      detail: session.UNSUPPORTED_SESSION_MESSAGE,
    })
    await expect(session.refreshAccessToken()).rejects.toMatchObject({ status: 0 })

    expect(refresh).not.toHaveBeenCalled()
  })
})
