import { beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { ProviderTypeView } from "@/domains/providers"
import { FAKE_PROVIDER_KEY, leakedAnywhere } from "@/test/workspaceHarness"
import { ProjectCapacityDialog } from "./ProjectCapacityDialog"

const api = vi.hoisted(() => ({
  listVaultKeys: vi.fn(), getKeyPool: vi.fn(), createVaultKey: vi.fn(), createKeyPool: vi.fn(),
  updateKeyPool: vi.fn(), startVaultOAuth: vi.fn(), pollVaultOAuth: vi.fn(),
}))
vi.mock("@/domains/vault", async (original) => ({ ...await original<typeof import("@/domains/vault")>(), ...api }))

const key = {
  id: "key-1", provider_type: "tavily", label: "Main", auth_mode: "api_key", status: "active",
  generation: 1, created_at: "2026-01-01", capacity: null, overcommit: true, contention_mode: "equal", pool_count: 0,
}

function open(provider = "tavily", onClose = vi.fn()) {
  return render(<ProjectCapacityDialog projectId="p1" projectName="Alpha" providers={[] as ProviderTypeView[]}
    provider={provider} onClose={onClose} onSaved={vi.fn()} />)
}

beforeEach(() => {
  vi.clearAllMocks()
  api.listVaultKeys.mockResolvedValue([])
  api.createVaultKey.mockResolvedValue(key)
  api.createKeyPool.mockResolvedValue({})
})

describe("ProjectProvidersPage.test.tsx", () => {
describe("ProjectProvidersPage private keys", () => {
  it("opens an existing pool using its credential ID after the key is renamed", async () => {
    api.listVaultKeys.mockResolvedValue([{ ...key, label: "Renamed" }])
    api.getKeyPool.mockResolvedValue({
      id: "pool", credential_id: key.id, provider_type: "tavily", project_id: "p1",
      label: "Alpha", rate: { limit: 60, window_seconds: 60 }, budget: null,
      budget_used_usd: 0, operations: ["search", "fetch"], operation_limits: null,
    })
    render(<ProjectCapacityDialog projectId="p1" projectName="Alpha" providers={[]} onClose={vi.fn()} onSaved={vi.fn()}
      pool={{ pool_id: "pool", label: "Alpha", provider_type: "tavily", key_label: "Old name",
        owner: { user_id: "u1", email: "admin@example.com" }, rate: { limit: 60, window_seconds: 60 },
        budget: null, budget_used: 0, operations: ["search", "fetch"] }} />)
    expect(await screen.findByText("Renamed")).toBeInTheDocument()
  })

  it("uses shared provider and key pickers with provider logos", async () => {
    api.listVaultKeys.mockResolvedValue([{ ...key, label: "First" }, { ...key, id: "key-2", label: "Second" }])
    const providers = [
      { providerType: "tavily", name: "Tavily" },
      { providerType: "you", name: "You.com" },
    ] as ProviderTypeView[]
    render(<ProjectCapacityDialog projectId="p1" projectName="Alpha" providers={providers} onClose={vi.fn()} onSaved={vi.fn()} />)
    const dialog = await screen.findByRole("dialog", { name: "Add Tavily capacity" })
    const provider = within(dialog).getByRole("combobox", { name: "Provider" })
    expect(within(provider).getByTestId("provider-logo-tavily")).toBeInTheDocument()
    await userEvent.click(provider)
    const you = within(dialog).getByRole("option", { name: "You.com" })
    expect(within(you).getByTestId("provider-logo-youcom")).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole("option", { name: "Tavily" }))
    await userEvent.click(within(dialog).getByRole("combobox", { name: "Key" }))
    await userEvent.click(within(dialog).getByRole("option", { name: "Second" }))
    expect(within(dialog).getByRole("combobox", { name: "Key" })).toHaveTextContent("Second")
    expect(within(dialog).queryByRole("listbox")).toBeNull()
    expect(dialog.querySelector("select")).toBeNull()
  })

  it("saves a key, shows only metadata, and keeps the key out of DOM, storage and URL", async () => {
    open()
    const dialog = await screen.findByRole("dialog", { name: "Add Tavily key" })
    const secret = within(dialog).getByLabelText("API key")
    expect(secret).toHaveAttribute("type", "password")
    await userEvent.type(secret, FAKE_PROVIDER_KEY)
    await userEvent.click(within(dialog).getByRole("button", { name: "Add key" }))
    expect(api.createVaultKey).toHaveBeenCalledWith({ provider_type: "tavily", label: "Tavily key",
      auth_mode: "api_key", secret: FAKE_PROVIDER_KEY, overcommit: true, contention_mode: "equal" })
    const pool = await screen.findByRole("dialog", { name: "Add Tavily capacity" })
    expect(within(pool).getByText("Alpha")).toBeInTheDocument()
    expect(within(pool).getByText("Main")).toBeInTheDocument()
    expect(within(pool).getByLabelText("Pool name")).toHaveValue("Alpha")
    expect(within(pool).getByRole("checkbox", { name: "Search" })).toBeChecked()
    expect(within(pool).getByRole("checkbox", { name: "Fetch" })).toBeChecked()
    expect(within(pool).queryByLabelText("Search requests")).toBeNull()
    expect(leakedAnywhere(FAKE_PROVIDER_KEY)).toEqual([])
    await userEvent.click(within(pool).getByRole("button", { name: "Create pool" }))
    await waitFor(() => expect(api.createKeyPool).toHaveBeenCalledWith("key-1", expect.objectContaining({
      project_id: "p1", operations: ["search", "fetch"],
    })))
  })

  it("clears the key after a failed save and shows no server detail", async () => {
    api.createVaultKey.mockRejectedValue(new Error("secret-value"))
    open()
    const dialog = await screen.findByRole("dialog", { name: "Add Tavily key" })
    await userEvent.type(within(dialog).getByLabelText("API key"), "secret-value")
    await userEvent.click(within(dialog).getByRole("button", { name: "Add key" }))
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("The key did not save")
    expect(within(dialog).getByLabelText("API key")).toHaveValue("")
    expect(document.body.textContent).not.toContain("secret-value")
  })

  it("offers OAuth only for Parallel and then sends no secret", async () => {
    api.createVaultKey.mockResolvedValue({ ...key, provider_type: "parallel", auth_mode: "oauth" })
    api.startVaultOAuth.mockResolvedValue({ user_code: "ABCD", verification_uri: "https://example.com", interval: 0.01, expires_in: 60 })
    api.pollVaultOAuth.mockResolvedValue({ status: "connected" })
    open("parallel")
    const dialog = await screen.findByRole("dialog", { name: "Add Parallel key" })
    expect(within(dialog).queryByLabelText("API key")).toBeNull()
    await userEvent.click(within(dialog).getByRole("button", { name: "Connect" }))
    expect(await screen.findByRole("dialog", { name: "Add Parallel capacity" })).toBeInTheDocument()
    expect(api.createVaultKey).toHaveBeenCalledWith(expect.objectContaining({ provider_type: "parallel", auth_mode: "oauth" }))
    expect(api.createVaultKey.mock.calls[0]?.[0]).not.toHaveProperty("secret")
    expect(api.startVaultOAuth).toHaveBeenCalled()
  })

  it("drops a typed key on cancel", async () => {
    const close = vi.fn()
    const view = open("tavily", close)
    const dialog = await screen.findByRole("dialog", { name: "Add Tavily key" })
    await userEvent.type(within(dialog).getByLabelText("API key"), "secret-value")
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }))
    expect(close).toHaveBeenCalled()
    view.unmount()
    expect(document.body.textContent).not.toContain("secret-value")
    expect(api.createVaultKey).not.toHaveBeenCalled()
  })
})
})
