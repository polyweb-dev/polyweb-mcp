import { describe, it, expect, afterEach, vi } from "vitest"
import { renderHook, act } from "@testing-library/react"
import { useAdminUsersController } from "./useAdminUsersController"
import { deferred, installFetchStub, ok, err } from "@/test/fetchMock"
import {
  adminAccountFixture,
  agentAccountFixture,
} from "@/test/authFixtures"

function stubProvision(handler?: (body: unknown) => Response | Promise<Response>) {
  return installFetchStub((req) => {
    if (req.method === "POST" && req.url === "/api/v1/users") {
      if (handler !== undefined) return handler(req.body)
      return ok(agentAccountFixture({ email: "new@example.com" }))
    }
    return err(404, { detail: "unhandled test route" })
  })
}

describe("useAdminUsersController", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("starts with empty drafts, no role draft, and no receipt", () => {
    stubProvision()
    const { result } = renderHook(() => useAdminUsersController())

    expect(result.current.email).toBe("")
    expect(result.current.password).toBe("")
    expect(result.current.confirmation).toBe("")
    expect("roleDraft" in result.current).toBe(false)
    expect(result.current.pending).toBe(false)
    expect(result.current.created).toBeNull()
    expect(result.current.error).toBeNull()
  })

  it("reports an error for an empty email without a fetch", async () => {
    const stub = stubProvision()
    const { result } = renderHook(() => useAdminUsersController())

    act(() => {
      result.current.setPassword("correct-horse-battery-99")
      result.current.setConfirmation("correct-horse-battery-99")
    })
    await act(async () => {
      await result.current.create()
    })

    expect(result.current.error).toBe("Enter an email address.")
    expect(result.current.created).toBeNull()
    expect(stub.requests).toHaveLength(0)
  })

  it.each([
    ["short", "a".repeat(11), "Use at least 12 characters for the password."],
    ["overlong", "a".repeat(129), "Use no more than 128 characters for the password."],
  ])("rejects a %s password with the registration copy and no fetch", async (_case, password, message) => {
    const stub = stubProvision()
    const { result } = renderHook(() => useAdminUsersController())

    act(() => {
      result.current.setEmail("new@example.com")
      result.current.setPassword(password)
      result.current.setConfirmation(password)
    })
    await act(async () => {
      await result.current.create()
    })

    expect(result.current.error).toBe(message)
    expect(result.current.created).toBeNull()
    expect(stub.requests).toHaveLength(0)
  })

  it("accepts the 12 and 128 character bounds", async () => {
    const stub = stubProvision()
    const { result } = renderHook(() => useAdminUsersController())

    for (const password of ["a".repeat(12), "a".repeat(128)]) {
      act(() => {
        result.current.setEmail("new@example.com")
        result.current.setPassword(password)
        result.current.setConfirmation(password)
      })
      await act(async () => {
        await result.current.create()
      })
      expect(result.current.error).toBeNull()
    }
    expect(stub.requests).toHaveLength(2)
  })

  it("reports a mismatch without a fetch", async () => {
    const stub = stubProvision()
    const { result } = renderHook(() => useAdminUsersController())

    act(() => {
      result.current.setEmail("new@example.com")
      result.current.setPassword("correct-horse-battery-99")
      result.current.setConfirmation("different-horse-battery-11")
    })
    await act(async () => {
      await result.current.create()
    })

    expect(result.current.error).toBe("The two passwords do not match.")
    expect(stub.requests).toHaveLength(0)
  })

  it("creates the account with exactly the email and password JSON and clears passwords", async () => {
    const stub = stubProvision(() => ok(adminAccountFixture({ email: "new@example.com" })))
    const { result } = renderHook(() => useAdminUsersController())

    act(() => {
      result.current.setEmail("new@example.com")
      result.current.setPassword("correct-horse-battery-99")
      result.current.setConfirmation("correct-horse-battery-99")
    })
    await act(async () => {
      await result.current.create()
    })

    expect(stub.requests).toHaveLength(1)
    expect(stub.requests[0]).toMatchObject({ url: "/api/v1/users", method: "POST" })
    expect(stub.requests[0]?.body).toEqual({
      email: "new@example.com",
      password: "correct-horse-battery-99",
    })
    expect(result.current.created?.email).toBe("new@example.com")
    expect(result.current.password).toBe("")
    expect(result.current.confirmation).toBe("")
    expect(result.current.error).toBeNull()
    expect(result.current.pending).toBe(false)
  })

  it("changes the email draft and drops the old receipt", async () => {
    stubProvision(() => ok(agentAccountFixture({ email: "new@example.com" })))
    const { result } = renderHook(() => useAdminUsersController())

    act(() => {
      result.current.setEmail("new@example.com")
      result.current.setPassword("correct-horse-battery-99")
      result.current.setConfirmation("correct-horse-battery-99")
    })
    await act(async () => {
      await result.current.create()
    })
    expect(result.current.created).not.toBeNull()

    act(() => {
      result.current.setEmail("other@example.com")
    })
    expect(result.current.email).toBe("other@example.com")
    expect(result.current.created).toBeNull()
  })

  it("reports the safe server error on creation failure", async () => {
    stubProvision(() => err(400, { detail: "Email already registered" }))
    const { result } = renderHook(() => useAdminUsersController())

    act(() => {
      result.current.setEmail("dup@example.com")
      result.current.setPassword("correct-horse-battery-99")
      result.current.setConfirmation("correct-horse-battery-99")
    })
    await act(async () => {
      await result.current.create()
    })

    expect(result.current.error).toBe("Email already registered")
    expect(result.current.created).toBeNull()
    expect(result.current.pending).toBe(false)
  })

  it("shows the friendly rule without raw JSON for a coded password failure", async () => {
    stubProvision(() =>
      err(400, {
        detail: { code: "REGISTER_INVALID_PASSWORD", reason: "weak password" },
      })
    )
    const { result } = renderHook(() => useAdminUsersController())

    act(() => {
      result.current.setEmail("new@example.com")
      result.current.setPassword("correct-horse-battery-99")
      result.current.setConfirmation("correct-horse-battery-99")
    })
    await act(async () => {
      await result.current.create()
    })

    expect(result.current.error).toBe(
      "Use 12 to 128 characters with an upper-case letter, a lower-case letter, a digit, and a symbol."
    )
    expect(result.current.error ?? "").not.toContain("REGISTER_INVALID_PASSWORD")
    expect(result.current.error ?? "").not.toContain("{")
    expect(result.current.created).toBeNull()
  })

  it("shows the friendly duplicate text for a coded duplicate email", async () => {
    stubProvision(() => err(400, { detail: { code: "REGISTER_USER_ALREADY_EXISTS" } }))
    const { result } = renderHook(() => useAdminUsersController())

    act(() => {
      result.current.setEmail("dup@example.com")
      result.current.setPassword("correct-horse-battery-99")
      result.current.setConfirmation("correct-horse-battery-99")
    })
    await act(async () => {
      await result.current.create()
    })

    expect(result.current.error).toBe(
      "That email address already has an account. Sign in instead."
    )
    expect(result.current.created).toBeNull()
  })

  it("shows the friendly configuration state when the secret is missing", async () => {
    stubProvision(() => err(503, { detail: "account authentication is not configured" }))
    const { result } = renderHook(() => useAdminUsersController())

    act(() => {
      result.current.setEmail("new@example.com")
      result.current.setPassword("correct-horse-battery-99")
      result.current.setConfirmation("correct-horse-battery-99")
    })
    await act(async () => {
      await result.current.create()
    })

    expect(result.current.error).toBe(
      "Sign-in is not ready yet. Set FREESEARCH_AUTH_JWT_SECRET on the server, then restart the API."
    )
    expect(result.current.created).toBeNull()
  })

  it("prevents a duplicate submit while pending", async () => {
    const gate = deferred<Response>()
    const stub = stubProvision(() => gate.promise)
    const { result } = renderHook(() => useAdminUsersController())

    act(() => {
      result.current.setEmail("new@example.com")
      result.current.setPassword("correct-horse-battery-99")
      result.current.setConfirmation("correct-horse-battery-99")
    })
    let first: Promise<void> | null = null
    act(() => {
      first = result.current.create()
    })
    await act(async () => {
      await result.current.create()
    })
    gate.resolve(ok(agentAccountFixture({ email: "new@example.com" })))
    await act(async () => {
      await first
    })

    expect(stub.requests).toHaveLength(1)
  })

  it("clears the receipt and the error when the email changes", async () => {
    stubProvision(() => ok(agentAccountFixture({ email: "new@example.com" })))
    const { result } = renderHook(() => useAdminUsersController())

    act(() => {
      result.current.setEmail("new@example.com")
      result.current.setPassword("correct-horse-battery-99")
      result.current.setConfirmation("correct-horse-battery-99")
    })
    await act(async () => {
      await result.current.create()
    })
    expect(result.current.created).not.toBeNull()

    act(() => {
      result.current.setEmail("other@example.com")
    })
    expect(result.current.created).toBeNull()
    expect(result.current.error).toBeNull()
  })
})
