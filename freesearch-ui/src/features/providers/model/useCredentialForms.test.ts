import { act, renderHook } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import type { ActionStatus } from "./useActionStatus"
import type { CredentialRoutes } from "./credentialRoutes"
import { useCredentialForms } from "./useCredentialForms"

function setup() {
  const routes: CredentialRoutes = {
    create: vi.fn().mockResolvedValue({}),
    rotate: vi.fn().mockResolvedValue({}),
    remove: vi.fn().mockResolvedValue(undefined),
    disconnect: vi.fn().mockResolvedValue(undefined),
    oauthBase: (id) => `/keys/${id}`,
  }
  const status: ActionStatus = { pending: false, message: null, notice: null, begin: vi.fn(), finish: vi.fn() }
  return { routes, status, reload: vi.fn() }
}

const input = { providerType: "brave", label: "Team", authMode: "api_key" as const, secret: "fake-test-key" }

describe("useCredentialForms Add key control", () => {
  it("closes a page-header-controlled dialog only after a successful save", async () => {
    const { routes, status, reload } = setup()
    const onOpenChange = vi.fn()
    const { result } = renderHook(() => useCredentialForms(routes, reload, status, { open: true, onOpenChange }))
    expect(result.current.adding).toBe(true)
    await act(async () => { expect(await result.current.create(input)).toBe(true) })
    expect(onOpenChange).toHaveBeenCalledWith(false)
    expect(routes.create).toHaveBeenCalledWith(input)
    expect(reload).toHaveBeenCalledOnce()
    expect(JSON.stringify(result.current)).not.toContain(input.secret)
  })

  it("keeps a controlled dialog open on failure and clears the error on cancel", async () => {
    const { routes, status, reload } = setup()
    vi.mocked(routes.create).mockRejectedValue(new Error("Save failed"))
    const onOpenChange = vi.fn()
    const { result } = renderHook(() => useCredentialForms(routes, reload, status, { open: true, onOpenChange }))
    await act(async () => { expect(await result.current.create(input)).toBe(false) })
    expect(onOpenChange).not.toHaveBeenCalled()
    expect(result.current.formError).not.toBeNull()
    act(() => result.current.openAdd(false))
    expect(onOpenChange).toHaveBeenCalledWith(false)
    expect(result.current.formError).toBeNull()
  })

  it("keeps local dialog state for project and standalone key pages", () => {
    const { routes, status, reload } = setup()
    const { result } = renderHook(() => useCredentialForms(routes, reload, status))
    act(() => result.current.openAdd(true))
    expect(result.current.adding).toBe(true)
    act(() => result.current.openAdd(false))
    expect(result.current.adding).toBe(false)
  })
})
