import { describe, expect, it } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { SettingsView } from "./SettingsView"

const seedProviderNames = [
  "Brave Search",
  "Keenable",
  "Tavily",
  "Exa",
  "Firecrawl",
  "You.com",
  "Parallel",
]

const renderSettings = () =>
  render(
    <FreeSearchProvider>
      <SettingsView />
    </FreeSearchProvider>
  )

function findProviderRow(provider: string): HTMLElement {
  const providerName = screen.getByText(provider, { exact: true })
  let current = providerName.parentElement

  while (current && current !== document.body) {
    const hasGlobalLabel = within(current).queryByText("Global", { exact: true })
    const hasSearchLabel = within(current).queryByText("Search", { exact: true })
    const hasOperationButton = within(current).queryAllByRole("button", { name: /^On$/ }).length > 0
    if (hasGlobalLabel && hasSearchLabel && hasOperationButton) return current
    current = current.parentElement
  }

  throw new Error(`Provider registry row not found for ${provider}`)
}

function findKeyCard(provider: string): HTMLElement {
  const providerName = screen.getByText(provider, { exact: true })
  let current = providerName.parentElement

  while (current && current !== document.body) {
    if (current.querySelector('input[type="password"]')) return current
    current = current.parentElement
  }

  throw new Error(`Key card not found for ${provider}`)
}

describe("SettingsView", () => {
  it("renders exactly Providers, Keys, and Failover tabs", () => {
    renderSettings()

    expect(screen.getAllByRole("tab")).toHaveLength(3)
    for (const label of ["Providers", "Keys", "Failover"]) {
      expect(screen.getByRole("tab", { name: new RegExp(`^${label}$`) })).toBeInTheDocument()
    }
    expect(screen.queryByRole("tab", { name: /^Cache$/ })).not.toBeInTheDocument()
    expect(screen.queryByRole("heading", { name: /^Cache$/ })).not.toBeInTheDocument()
  })

  it("shows all seeded providers with operation segments and no add or delete actions", () => {
    renderSettings()

    for (const provider of seedProviderNames) {
      expect(screen.getByText(provider, { exact: true })).toBeInTheDocument()
    }
    for (let priority = 1; priority <= seedProviderNames.length; priority += 1) {
      expect(screen.getByText(`P${priority}`, { exact: true })).toBeInTheDocument()
    }

    expect(screen.getAllByRole("switch")).toHaveLength(7)
    expect(screen.getAllByText("Not supported", { exact: true })).toHaveLength(2)
    expect(screen.getAllByRole("button", { name: /^On$/ })).toHaveLength(11)
    expect(screen.getAllByRole("button", { name: /^Off$/ })).toHaveLength(11)
    expect(screen.queryByRole("button", { name: /add provider/i })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /remove|delete/i })).not.toBeInTheDocument()
  })

  it("labels every global switch with its provider name", () => {
    renderSettings()

    for (const provider of seedProviderNames) {
      expect(
        screen.getByRole("switch", { name: `${provider} global routing` })
      ).toBeInTheDocument()
    }
  })

  it("labels every provider connection test button with its provider name", () => {
    renderSettings()

    for (const provider of seedProviderNames) {
      expect(
        screen.getByRole("button", { name: `${provider} connection` })
      ).toBeInTheDocument()
    }
  })

  it("labels every key input with its provider name", async () => {
    const user = userEvent.setup()
    renderSettings()
    await user.click(screen.getByRole("tab", { name: /^Keys$/ }))

    for (const provider of seedProviderNames) {
      expect(
        screen.getByRole("textbox", { name: `${provider} API key` })
      ).toBeInTheDocument()
    }
  })

  it("disables the boundary priority arrows", () => {
    renderSettings()

    const firstRow = findProviderRow("Brave Search")
    const lastRow = findProviderRow("Parallel")
    expect(within(firstRow).getByRole("button", { name: /up/i })).toBeDisabled()
    expect(within(lastRow).getByRole("button", { name: /down/i })).toBeDisabled()
  })

  it("swaps a middle provider upward and updates rendered priorities", async () => {
    const user = userEvent.setup()
    renderSettings()

    await user.click(within(findProviderRow("Tavily")).getByRole("button", { name: /up/i }))

    const providerTextPattern = /^(Brave Search|Tavily|Keenable|Exa|Firecrawl|You[.]com|Parallel)$/
    expect(screen.getAllByText(providerTextPattern)).toHaveLength(7)
    const renderedProviderOrder = screen
      .getAllByText(providerTextPattern)
      .map((provider) => provider.textContent)
    expect(renderedProviderOrder).toEqual([
      "Brave Search",
      "Tavily",
      "Keenable",
      "Exa",
      "Firecrawl",
      "You.com",
      "Parallel",
    ])
    expect(within(findProviderRow("Tavily")).getByText("P2", { exact: true })).toBeInTheDocument()
    expect(within(findProviderRow("Keenable")).getByText("P3", { exact: true })).toBeInTheDocument()
  })

  it("disables operation segments when a provider is globally disabled", async () => {
    const user = userEvent.setup()
    renderSettings()

    const row = findProviderRow("Brave Search")
    await user.click(within(row).getAllByRole("switch")[0]!)

    const searchOperation = within(row).getByText("Search", { exact: true }).parentElement!
    expect(within(searchOperation).getByRole("button", { name: /^On$/ })).toBeDisabled()
    expect(within(searchOperation).getByRole("button", { name: /^Off$/ })).toBeDisabled()
  })

  it("flips and retains a supported provider operation segment", async () => {
    const user = userEvent.setup()
    renderSettings()

    const row = findProviderRow("Brave Search")
    const searchOperation = within(row).getByText("Search", { exact: true }).parentElement!
    const off = within(searchOperation).getByRole("button", { name: /^Off$/ })
    await user.click(off)
    expect(off).toHaveAttribute("aria-pressed", "true")

    await user.click(screen.getByRole("tab", { name: /^Keys$/ }))
    await user.click(screen.getByRole("tab", { name: /^Providers$/ }))

    const providersRow = findProviderRow("Brave Search")
    const providersSearchOperation = within(providersRow).getByText("Search", { exact: true }).parentElement!
    expect(
      within(providersSearchOperation).getByRole("button", { name: /^Off$/ })
    ).toHaveAttribute("aria-pressed", "true")
  })

  it("renders the write-only key vault with statuses, masked fingerprints, and no reveal actions", async () => {
    const user = userEvent.setup()
    renderSettings()
    await user.click(screen.getByRole("tab", { name: /^Keys$/ }))

    expect(screen.getAllByText("Stored", { exact: true })).toHaveLength(4)
    expect(screen.getAllByText("Keyless", { exact: true })).toHaveLength(1)
    expect(screen.getAllByText("Missing", { exact: true })).toHaveLength(2)
    expect(screen.getByText("BSA_live_••••••••3f8a", { exact: true })).toBeInTheDocument()
    expect(screen.getAllByText(/••••••••/).length).toBeGreaterThan(0)

    const body = document.body.textContent ?? ""
    for (const forbidden of ["Copy", "Burn", "Reveal", "shown once"]) {
      expect(body).not.toContain(forbidden)
    }
  })

  it("saves a raw key as a masked Stored fingerprint and clears the write-only input", async () => {
    const user = userEvent.setup()
    renderSettings()
    await user.click(screen.getByRole("tab", { name: /^Keys$/ }))

    const card = findKeyCard("You.com")
    const input = card.querySelector('input[type="password"]') as HTMLInputElement
    await user.type(input, "yc_live_secret_key_6789")
    await user.click(within(card).getByRole("button", { name: /^Save$/ }))

    expect(within(card).getByText("Stored", { exact: true })).toBeInTheDocument()
    expect(within(card).getByText("yc_l_••••••••6789", { exact: true })).toBeInTheDocument()
    expect(input).toHaveValue("")
    expect(document.body.textContent).not.toContain("yc_live_secret_key_6789")
  })

  it("renders failover switches with descriptions and timeout policy rows", async () => {
    const user = userEvent.setup()
    renderSettings()
    await user.click(screen.getByRole("tab", { name: /^Failover$/ }))

    const labels = [
      "Fallback chaining",
      "Failover on rate limit (429)",
      "Failover on timeout",
      "Failover on server error (5xx)",
    ]
    for (const label of labels) {
      const labelNode = screen.getByText(label, { exact: true })
      expect(labelNode).toBeInTheDocument()
      const parentText = labelNode.parentElement?.textContent?.trim() ?? ""
      expect(parentText.startsWith(label)).toBe(true)
      expect(parentText.length).toBeGreaterThan(label.length)
    }

    expect(screen.getByText("Cascade depth", { exact: true })).toBeInTheDocument()
    expect(screen.getByText("Timeout budget", { exact: true })).toBeInTheDocument()
    expect(screen.getByText("3,000 ms", { exact: true })).toBeInTheDocument()
  })
})
