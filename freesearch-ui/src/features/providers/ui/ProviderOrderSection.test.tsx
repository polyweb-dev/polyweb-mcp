import { beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render as renderComponent, screen, waitFor, within } from "@testing-library/react"
import type { ReactNode } from "react"
import { Link, MemoryRouter, useLocation } from "react-router"
import userEvent from "@testing-library/user-event"
import type { ProjectOrder } from "@/domains/routing"
import { ApiError } from "@/shared/api/http"
import type { ProjectProvidersController } from "../model/useProjectProvidersController"
import { ProviderOrderSection } from "./ProviderOrderSection"
import type { ProviderOrderContext } from "./ProviderOrderSection"

const mocks = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), toast: vi.fn() }))
const render = (ui: ReactNode) => renderComponent(ui, { wrapper: MemoryRouter })

function LocationProbe() {
  const location = useLocation()
  return <><output aria-label="Current query">{location.search}</output><Link to="?operation=fetch">Open Fetch order</Link></>
}
vi.mock("@/domains/routing", () => ({ getProjectOrder: mocks.get, putProjectOrder: mocks.put }))
vi.mock("@/shared/notifications/useNotifications", () => ({ useNotifications: () => ({ showToast: mocks.toast }) }))

function document(): ProjectOrder {
  return {
    revision: 1,
    search: {
      strategy: "lowest_cost", hasSavedCustom: false, notAllowed: ["brave"],
      providers: [
        { provider: "tavily", name: "Tavily", callCostUsd: "0.0076", keyless: false },
        { provider: "exa", name: "Exa", callCostUsd: null, keyless: false },
      ],
    },
    fetch: {
      strategy: "lowest_cost", hasSavedCustom: false, notAllowed: [],
      providers: [{ provider: "exa", name: "Exa", callCostUsd: 0, keyless: false }],
    },
  }
}

function context(overrides: Partial<ProviderOrderContext> = {}): ProviderOrderContext {
  return {
    projectId: "project", providers: ["tavily", "exa"].map((providerType) => ({
      providerType, name: providerType, keyless: providerType === "tavily", capability: ["search", "fetch"],
      callCostUsd: { search: providerType === "tavily" ? "0.0076" : null, fetch: 0 },
      keylessCallCostUsd: providerType === "tavily" ? { search: 0, fetch: 0 } : {},
      killSwitch: false, systemEnabledOperations: ["search", "fetch"], available: true, enabled: true,
      credentials: [], bindings: [], effectiveOperations: ["search", "fetch"],
    })), canConfigure: true, canManagePrivate: false,
    controller: { bindingStatus: { pending: false }, credentialsById: new Map() } as unknown as ProjectProvidersController,
    ...overrides,
  }
}

async function selectOption(label: string) {
  const user = userEvent.setup()
  await user.click(screen.getByRole("combobox", { name: "Order by" }))
  await user.click(screen.getByRole("option", { name: new RegExp(label) }))
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.get.mockResolvedValue(document())
})

describe("Provider order section", () => {
  it.each(["", "?operation=invalid", "?operation=search", "?operation=fetch"])("selects the tab from %s and syncs the query on changes", async (query) => {
    renderComponent(<><ProviderOrderSection context={context()} /><LocationProbe /></>, {
      wrapper: ({ children }) => <MemoryRouter initialEntries={[`/p/project/providers${query}`]}>{children}</MemoryRouter>,
    })
    const initialTab = query === "?operation=fetch" ? "Fetch 1" : "Search 2"
    expect(await screen.findByRole("tab", { name: initialTab })).toHaveAttribute("aria-selected", "true")
    await userEvent.click(screen.getByRole("tab", { name: "Search 2" }))
    await userEvent.click(screen.getByRole("tab", { name: "Fetch 1" }))
    expect(screen.getByLabelText("Current query")).toHaveTextContent("?operation=fetch")
    await userEvent.click(screen.getByRole("tab", { name: "Search 2" }))
    expect(screen.getByLabelText("Current query")).toHaveTextContent("?operation=search")
    await userEvent.click(screen.getByRole("link", { name: "Open Fetch order" }))
    expect(screen.getByRole("tab", { name: "Fetch 1" })).toHaveAttribute("aria-selected", "true")
  })

  it("shows keyless tags and free capacity instead of a pool name", async () => {
    const order = document()
    order.search.providers[0] = { provider: "tavily", name: "Tavily", callCostUsd: 0, keyless: true }
    mocks.get.mockResolvedValue(order)
    render(<ProviderOrderSection context={context({ renderPool: () => "Pool name" })} />)
    const table = await screen.findByRole("table", { name: "Search provider order" })
    const row = within(table).getByText("Tavily").closest("tr")
    if (!row) throw new Error("Missing Tavily row")
    expect(within(row).getByText("No key needed")).toBeInTheDocument()
    expect(within(row).getByText("No pool needed")).toBeInTheDocument()
    expect(within(row).queryByText("Pool name")).toBeNull()
    expect(within(table).getByText("Pool name")).toBeInTheDocument()
  })

  it("shows separate tabs, costs and providers excluded by their pools", async () => {
    render(<ProviderOrderSection context={context()} />)
    expect(await screen.findByRole("tab", { name: "Search 2" })).toBeInTheDocument()
    expect(screen.getByText("$0.0076")).toBeInTheDocument()
    expect(screen.getByText(/Not in this list: Brave/)).toHaveTextContent("Its pool does not allow Search")
    await userEvent.click(screen.getByRole("tab", { name: "Fetch 1" }))
    expect(screen.getByText("Free")).toBeInTheDocument()
    expect(screen.queryByText(/Not in this list/)).not.toBeInTheDocument()
  })

  it("saves a preset and undoes it", async () => {
    const changed = document()
    changed.search.strategy = "free_first"
    mocks.put.mockResolvedValueOnce(changed).mockResolvedValueOnce(document())
    render(<ProviderOrderSection context={context()} />)
    await screen.findByRole("tab", { name: "Search 2" })
    await selectOption("Free first")
    await screen.findByRole("button", { name: "Undo" })
    expect(screen.queryByText(/Order set by/)).toBeNull()
    expect(mocks.put).toHaveBeenNthCalledWith(1, "project", "search", { strategy: "free_first" })
    await userEvent.click(screen.getByRole("button", { name: "Undo" }))
    await waitFor(() => expect(mocks.put).toHaveBeenNthCalledWith(2, "project", "search", { strategy: "lowest_cost" }))
  })

  it("saves an arrow move as a full custom order", async () => {
    const changed = document()
    changed.search.strategy = "custom"
    changed.search.hasSavedCustom = true
    changed.search.providers.reverse()
    mocks.put.mockResolvedValue(changed)
    render(<ProviderOrderSection context={context()} />)
    await userEvent.click(await screen.findByRole("button", { name: "Move Exa priority up" }))
    await waitFor(() => expect(mocks.put).toHaveBeenCalledWith("project", "search", { strategy: "custom", order: ["exa", "tavily"] }))
    expect(await screen.findByRole("combobox", { name: "Order by" })).toHaveTextContent("Custom order")
    expect(screen.queryByRole("button", { name: "Undo" })).not.toBeInTheDocument()
  })

  it("saves a drag as a full custom order", async () => {
    mocks.put.mockResolvedValue(document())
    render(<ProviderOrderSection context={context()} />)
    const grip = await screen.findByLabelText("Drag Exa to change priority")
    const rows = screen.getByRole("table", { name: "Search provider order" })
    const target = within(rows).getByText("Tavily").closest("tr")
    const dataTransfer = { setData: vi.fn(), effectAllowed: "", dropEffect: "" }
    fireEvent.dragStart(grip, { dataTransfer })
    if (!target) throw new Error("Missing target row")
    fireEvent.dragOver(target, { dataTransfer })
    fireEvent.drop(target, { dataTransfer })
    await waitFor(() => expect(mocks.put).toHaveBeenCalledWith("project", "search", { strategy: "custom", order: ["exa", "tavily"] }))
  })

  it("reloads after a conflict", async () => {
    mocks.put.mockRejectedValue(new ApiError(409, "stale", null))
    render(<ProviderOrderSection context={context()} />)
    await screen.findByRole("tab", { name: "Search 2" })
    await selectOption("Free first")
    await waitFor(() => expect(mocks.get).toHaveBeenCalledTimes(2))
    expect(mocks.toast).toHaveBeenCalledWith("The providers changed. The list is reloaded.", "error")
  })

  it("retries a failed load", async () => {
    mocks.get.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(document())
    render(<ProviderOrderSection context={context()} />)
    expect(await screen.findByRole("alert")).toHaveTextContent("Cannot load the provider order")
    await userEvent.click(screen.getByRole("button", { name: "Retry" }))
    expect(await screen.findByRole("tab", { name: "Search 2" })).toBeInTheDocument()
  })

  it("shows a save error without changing the order", async () => {
    mocks.put.mockRejectedValue(new ApiError(500, "Offline", null))
    render(<ProviderOrderSection context={context()} />)
    await screen.findByRole("tab", { name: "Search 2" })
    await selectOption("Free first")
    await waitFor(() => expect(mocks.toast).toHaveBeenCalledWith("The server did not save the order. Offline", "error"))
    expect(screen.getByRole("combobox", { name: "Order by" })).toHaveTextContent("Lowest cost")
  })

  it("restores a saved custom order without sending a list", async () => {
    const saved = document()
    saved.search.hasSavedCustom = true
    mocks.get.mockResolvedValue(saved)
    mocks.put.mockResolvedValue({ ...saved, search: { ...saved.search, strategy: "custom" } })
    render(<ProviderOrderSection context={context()} />)
    await screen.findByRole("tab", { name: "Search 2" })
    await selectOption("Custom order")
    await waitFor(() => expect(mocks.put).toHaveBeenCalledWith("project", "search", { strategy: "custom" }))
  })

  it("disables editing for a read-only user", async () => {
    render(<ProviderOrderSection context={context({ canConfigure: false })} />)
    expect(await screen.findByText("Order: Lowest cost")).toBeInTheDocument()
    expect(screen.queryByRole("combobox", { name: "Order by" })).toBeNull()
    expect(screen.queryByRole("button", { name: /priority up/ })).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/Drag .* priority/)).not.toBeInTheDocument()
    expect(screen.queryByRole("columnheader", { name: "On" })).toBeNull()
  })

  it("shows empty state copy for the owner and other users", async () => {
    const empty = document()
    empty.search.providers = []
    mocks.get.mockResolvedValue(empty)
    const { rerender } = render(<ProviderOrderSection context={context({ owner: "owner@example.com" })} />)
    expect(await screen.findByText(/Ask owner@example.com/)).toBeInTheDocument()
    rerender(<ProviderOrderSection context={context({ isOwner: true })} />)
    expect(screen.getByRole("link", { name: "Change pools" })).toHaveAttribute("href", "/account/keys")
  })

  it("shows the warning when the project has no providers", async () => {
    const empty = document()
    empty.search.providers = []
    empty.search.notAllowed = []
    empty.fetch.providers = []
    mocks.get.mockResolvedValue(empty)
    render(<ProviderOrderSection context={context()} />)
    await waitFor(() => expect(mocks.get).toHaveBeenCalled())
    expect(await screen.findByText("No provider can serve Search in this project")).toBeInTheDocument()
  })

  it("explains a system-disabled keyless provider and offers an admin link", async () => {
    const order = document()
    order.search.providers = [{ provider: "tavily", name: "Tavily", callCostUsd: 0, keyless: true }]
    mocks.get.mockResolvedValue(order)
    const provider = { providerType: "tavily", name: "Tavily", keyless: true, capability: ["search", "fetch"],
      killSwitch: false, systemEnabledOperations: ["fetch"], available: true, enabled: false,
      credentials: [], bindings: [], effectiveOperations: [] } as ProviderOrderContext["providers"][number]
    const addCapacity = vi.fn()
    const { rerender } = render(<ProviderOrderSection context={context({ providers: [provider], isOwner: true, canEditSystem: true, addCapacity, poolOperations: () => undefined })} />)
    expect(await screen.findByText("No provider can serve Search in this project")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Turn on in System Providers" })).toHaveAttribute("href", "/system/providers")
    await userEvent.click(screen.getByRole("button", { name: "Add capacity" }))
    expect(addCapacity).toHaveBeenCalledOnce()
    rerender(<ProviderOrderSection context={context({ providers: [provider], canEditSystem: false, poolOperations: () => undefined })} />)
    expect(screen.queryByRole("link", { name: "Turn on in System Providers" })).toBeNull()
    expect(screen.getByText(/Off in system/)).toBeInTheDocument()
  })

  it("does not warn when an effective provider can serve the operation", async () => {
    const provider = { providerType: "tavily", name: "Tavily", keyless: false, capability: ["search", "fetch"],
      killSwitch: false, systemEnabledOperations: ["search", "fetch"], available: true, enabled: true,
      credentials: [], bindings: [], effectiveOperations: ["search"] } as ProviderOrderContext["providers"][number]
    render(<ProviderOrderSection context={context({ providers: [provider] })} />)
    await screen.findByRole("table", { name: "Search provider order" })
    expect(screen.queryByText("No provider can serve Search in this project")).toBeNull()
    await userEvent.click(screen.getByRole("tab", { name: "Fetch 1" }))
    expect(screen.getByText("No provider can serve Fetch in this project")).toBeInTheDocument()
  })

  it("places off providers below serving providers without a rank or drag control", async () => {
    const makeProvider = (providerType: string, enabled: boolean) => ({
      providerType, name: providerType, keyless: false, capability: ["search"],
      killSwitch: false, systemEnabledOperations: ["search"], available: true, enabled,
      credentials: [], bindings: [], effectiveOperations: enabled ? ["search"] : [],
    } as ProviderOrderContext["providers"][number])
    render(<ProviderOrderSection context={context({ providers: [makeProvider("tavily", false), makeProvider("exa", true)] })} />)
    const table = await screen.findByRole("table", { name: "Search provider order" })
    const rows = within(table).getAllByRole("row")
    expect(rows[1]).toHaveTextContent("Exa")
    expect(rows[2]).toHaveTextContent("Tavily")
    expect(within(rows[2] as HTMLElement).getByLabelText("Not in dispatch order")).toBeInTheDocument()
    expect(within(rows[2] as HTMLElement).queryByLabelText(/Drag/)).toBeNull()
  })

  it("uses a disabled on switch for keyless access and the catalog price instead of the order price", async () => {
    const order = document()
    order.search.providers[0] = { provider: "tavily", name: "Tavily", callCostUsd: "99", keyless: true }
    mocks.get.mockResolvedValue(order)
    render(<ProviderOrderSection context={context({ isOwner: true, poolOperations: () => undefined })} />)
    const table = await screen.findByRole("table", { name: "Search provider order" })
    const control = within(table).getByRole("switch", { name: "Use Tavily for Search" })
    expect(control).toBeChecked()
    expect(control).toBeDisabled()
    expect(screen.getByTitle("Always on: no key needed")).toContainElement(control)
    expect(within(table).getByText("Free without a key")).toBeInTheDocument()
    expect(within(table).queryByText(/99/)).toBeNull()
  })

  it("keeps the same column widths and minimum row height across Search and Fetch", async () => {
    render(<ProviderOrderSection context={context()} />)
    const search = await screen.findByRole("table", { name: "Search provider order" })
    expect(search).toHaveClass("table-fixed")
    const widths = Array.from(search.querySelectorAll("col")).map((col) => col.className)
    expect(search.querySelector("tbody tr")).toHaveClass("h-[60px]")
    await userEvent.click(screen.getByRole("tab", { name: "Fetch 1" }))
    const fetch = screen.getByRole("table", { name: "Fetch provider order" })
    expect(fetch).toHaveClass("table-fixed")
    expect(Array.from(fetch.querySelectorAll("col")).map((col) => col.className)).toEqual(widths)
    expect(fetch.querySelector("tbody tr")).toHaveClass("h-[60px]")
  })
})
