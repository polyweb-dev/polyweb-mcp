import { describe, expect, it, vi } from "vitest"
import { projectCredentialRoutes } from "./credentialRoutes"

describe("projectCredentialRoutes", () => {
  it("rejects retired project-key actions without making a request", async () => {
    const fetch = vi.fn()
    vi.stubGlobal("fetch", fetch)
    const routes = projectCredentialRoutes()
    const input = { providerType: "tavily", label: "Key", authMode: "api_key" as const, secret: "test" }
    await expect(routes.create(input)).rejects.toThrow("Manage keys in Account")
    await expect(routes.rotate("id", 1, "test")).rejects.toThrow("Manage keys in Account")
    await expect(routes.remove("id")).rejects.toThrow("Manage keys in Account")
    await expect(routes.disconnect("id")).rejects.toThrow("Manage keys in Account")
    expect(() => routes.oauthBase("id")).toThrow("Manage keys in Account")
    expect(fetch).not.toHaveBeenCalled()
    vi.unstubAllGlobals()
  })
})
