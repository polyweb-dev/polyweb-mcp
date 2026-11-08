import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, renderHook } from "@testing-library/react"
import { installFetchStub, ok } from "@/test/fetchMock"
import { OAUTH_POLL_FAILED, OAUTH_START_FAILED, useCredentialOAuth } from "./useCredentialOAuth"

const BASE = "/api/v1/account/vault/keys/c1"
const KEY_ID = "c1"
const DEVICE = { user_code: "WDJB-MJHT", verification_uri: "https://auth.example.test/device", interval: 5, expires_in: 600, device_code: "fake-device-code" }

async function flush() {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
    await Promise.resolve()
  })
}

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

describe("useCredentialOAuth", () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it("polls at the server interval and stops when connected", async () => {
    const answers = [
      { credential_id: "c1", status: "pending", interval: 8 },
      { credential_id: "c1", status: "connected" },
    ]
    const stub = installFetchStub((req) => (req.url.endsWith("/device") ? ok(DEVICE, 201) : ok(answers.shift())))
    const onConnected = vi.fn()
    const { result } = renderHook(() => useCredentialOAuth({ base: KEY_ID, onConnected }))
    await flush()
    expect(result.current).toMatchObject({ phase: "polling", status: "pending", device: { userCode: "WDJB-MJHT" } })
    expect(JSON.stringify(result.current)).not.toContain("fake-device-code")

    await advance(4999)
    expect(stub.requestsTo(`${BASE}/oauth/poll`)).toHaveLength(0)
    await advance(1)
    expect(stub.requestsTo(`${BASE}/oauth/poll`)).toHaveLength(1)

    await advance(7999)
    expect(stub.requestsTo(`${BASE}/oauth/poll`)).toHaveLength(1)
    await advance(1)
    expect(stub.requestsTo(`${BASE}/oauth/poll`)).toHaveLength(2)
    expect(result.current).toMatchObject({ phase: "finished", status: "connected" })
    expect(onConnected).toHaveBeenCalledTimes(1)

    await advance(60_000)
    expect(stub.requestsTo(`${BASE}/oauth/poll`)).toHaveLength(2)
  })

  it("stops polling on unmount", async () => {
    const stub = installFetchStub((req) =>
      req.url.endsWith("/device") ? ok(DEVICE, 201) : ok({ credential_id: "c1", status: "pending", interval: 5 })
    )
    const { unmount } = renderHook(() => useCredentialOAuth({ base: KEY_ID }))
    await flush()
    await advance(5000)
    expect(stub.requestsTo(`${BASE}/oauth/poll`)).toHaveLength(1)
    unmount()
    await advance(60_000)
    expect(stub.requestsTo(`${BASE}/oauth/poll`)).toHaveLength(1)
  })

  it("expires after expires_in", async () => {
    const stub = installFetchStub((req) =>
      req.url.endsWith("/device") ? ok({ ...DEVICE, expires_in: 12 }, 201) : ok({ credential_id: "c1", status: "pending" })
    )
    const { result } = renderHook(() => useCredentialOAuth({ base: KEY_ID }))
    await flush()
    await advance(20_000)
    expect(result.current.phase).toBe("expired")
    const polls = stub.requestsTo(`${BASE}/oauth/poll`).length
    await advance(60_000)
    expect(stub.requestsTo(`${BASE}/oauth/poll`)).toHaveLength(polls)
  })

  it("reports a failed start and a failed poll", async () => {
    installFetchStub(() => new Response(null, { status: 500 }))
    const failedStart = renderHook(() => useCredentialOAuth({ base: KEY_ID }))
    await flush()
    expect(failedStart.result.current).toEqual({ phase: "failed", message: OAUTH_START_FAILED })
    failedStart.unmount()

    installFetchStub((req) => (req.url.endsWith("/device") ? ok(DEVICE, 201) : new Response(null, { status: 500 })))
    const failedPoll = renderHook(() => useCredentialOAuth({ base: KEY_ID }))
    await flush()
    await advance(5000)
    expect(failedPoll.result.current).toEqual({ phase: "failed", message: OAUTH_POLL_FAILED })
  })
})
