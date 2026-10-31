import { afterEach, describe, expect, it, vi } from "vitest"
import { act, renderHook, waitFor } from "@testing-library/react"
import { err, installFetchStub, ok } from "@/test/fetchMock"
import { PROJECT_ALPHA_ID, PROJECT_BETA_ID, apiKeyFixture } from "@/test/accessFixtures"
import { useProjectApiKeysController } from "./useProjectApiKeysController"
import type { UseProjectApiKeysControllerOptions } from "./useProjectApiKeysController"

/** Opaque stand-in for a one-time key; it is not a real credential. */
const ONE_TIME_VALUE = "fs_live_test-only-opaque-value"
const CREATOR = "11111111-1111-4111-8111-111111111111"

function installStub(issue: () => Response = () => ok({ ...apiKeyFixture(), key: ONE_TIME_VALUE }, 201)) {
  return installFetchStub((req) => {
    if (req.url.endsWith("/api-keys") && req.method === "GET") return ok([apiKeyFixture()])
    if (req.url.endsWith("/members")) {
      return ok([{ project_id: PROJECT_ALPHA_ID, user_id: CREATOR, email: "lead@example.com", status: "active", roles: [], version: 1 }])
    }
    if (req.url.endsWith("/api-keys") && req.method === "POST") return issue()
    return err(404, null)
  })
}

function renderController(overrides: Partial<UseProjectApiKeysControllerOptions> = {}) {
  const refreshAccess = vi.fn()
  const options: UseProjectApiKeysControllerOptions = {
    accountId: "acc",
    projectId: PROJECT_ALPHA_ID,
    refreshAccess,
    canReadMembers: true,
    ...overrides,
  }
  const hook = renderHook((props: UseProjectApiKeysControllerOptions) => useProjectApiKeysController(props), {
    initialProps: options,
  })
  return { ...hook, refreshAccess, options }
}

const ISSUE = { label: "CI", scopes: ["search.execute"] as const, expiry: { kind: "default" } as const }

afterEach(() => vi.unstubAllGlobals())

describe("useProjectApiKeysController", () => {
  it("loads the keys and the creator emails", async () => {
    installStub()
    const { result } = renderController()
    await waitFor(() => expect(result.current.keys.status).toBe("ready"))
    await waitFor(() => expect(result.current.emailsByUserId?.get(CREATOR)).toBe("lead@example.com"))
  })

  it("skips the member read without members.read", async () => {
    const stub = installStub()
    const { result } = renderController({ canReadMembers: false })
    await waitFor(() => expect(result.current.keys.status).toBe("ready"))
    expect(result.current.emailsByUserId).toBeNull()
    expect(stub.requests.some((req) => req.url.endsWith("/members"))).toBe(false)
  })

  it("holds the raw key only until the reveal closes", async () => {
    installStub()
    const { result } = renderController()
    let issued = false
    await act(async () => {
      issued = await result.current.issue(ISSUE)
    })
    expect(issued).toBe(true)
    expect(result.current.revealedKey).toBe(ONE_TIME_VALUE)
    expect(JSON.stringify(result.current.keys)).not.toContain(ONE_TIME_VALUE)
    act(() => result.current.dismissReveal())
    expect(result.current.revealedKey).toBeNull()
  })

  it("clears the raw key on a scope change, so it never returns to the first scope", async () => {
    installStub()
    const { result, rerender, options } = renderController()
    await act(async () => {
      await result.current.issue(ISSUE)
    })
    act(() => result.current.openRotate(apiKeyFixture()))
    expect(result.current.revealedKey).toBe(ONE_TIME_VALUE)

    rerender({ ...options, projectId: PROJECT_BETA_ID })
    expect(result.current.revealedKey).toBeNull()
    expect(result.current.rotatingKey).toBeNull()

    rerender(options)
    expect(result.current.revealedKey).toBeNull()
    await waitFor(() => expect(result.current.keys.status).toBe("ready"))
    expect(result.current.revealedKey).toBeNull()
  })

  it("maps a 403 to the permission copy and refreshes the access", async () => {
    installStub(() => err(403, null))
    const { result, refreshAccess } = renderController()
    let issued = true
    await act(async () => {
      issued = await result.current.issue(ISSUE)
    })
    expect(issued).toBe(false)
    expect(result.current.message).toBe("You no longer have permission for this action.")
    expect(result.current.revealedKey).toBeNull()
    expect(refreshAccess).toHaveBeenCalledTimes(1)
  })

  it("clears the message when the rotate dialog opens", async () => {
    installStub()
    const { result } = renderController()
    act(() => result.current.showMessage("Old failure"))
    act(() => result.current.openRotate(apiKeyFixture()))
    expect(result.current.message).toBeNull()
    expect(result.current.rotatingKey).not.toBeNull()
  })
})
