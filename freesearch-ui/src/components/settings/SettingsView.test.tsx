import React from "react"
import { describe, expect, it, afterEach, vi } from "vitest"
import { render, screen, within, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { SettingsView } from "./SettingsView"
import { installFetchStub, ok, err, deferred, type FetchStub } from "@/test/fetchMock"
import {
  allProvidersFixture,
  routingConfigFixture,
  dashboardFixture,
  secretStatusFixture,
} from "@/test/backendFixtures"

/**
 * RED update: every control is async against the live backend (mocked fetch).
 * Global switches PATCH with pending/disabled states + error toasts,
 * per-operation switches stay local-only and capability-gated, the key vault
 * renders server fingerprints with a Delete button and an
 * environment/dotenv-shadowing note, and the invented "3,000 ms" copy is gone.
 */
const seedProviderNames = [
  "Brave Search",
  "Keenable",
  "Tavily",
  "Exa",
  "Firecrawl",
  "You.com",
  "Parallel",
]

let secretSource: string = "keyring"
let patchGate: Promise<Response> | null = null

function renderSettings(): FetchStub {
  secretSource = "keyring"
  patchGate = null
  const stub = installFetchStub((req) => {
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(allProvidersFixture())
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
    if (req.method === "PATCH" && req.url.startsWith("/api/v1/providers/")) {
      if (patchGate) return patchGate
      return ok({ ...allProvidersFixture()[0], ...(req.body as object) })
    }
    if (req.url.endsWith("/secret") && req.method === "PUT") {
      const provider = req.url.split("/").at(-2) ?? "unknown"
      return ok(
        secretStatusFixture({
          provider,
          fingerprint: `${provider.slice(0, 3).toUpperCase()}_••••••••a1b2`,
          source: secretSource,
        })
      )
    }
    if (req.url.endsWith("/secret") && req.method === "DELETE") {
      const provider = req.url.split("/").at(-2) ?? "unknown"
      return ok(
        secretStatusFixture({
          provider,
          presence: "missing",
          fingerprint: null,
          source: "none",
        })
      )
    }
    if (req.method === "POST" && req.url.endsWith("/test")) {
      return ok({
        provider: "x",
        ok: true,
        status: "healthy",
        latency_ms: 142,
        checked_at: "2026-09-06T10:04:00Z",
        detail: null,
      })
    }
    if (req.method === "PUT" && req.url === "/api/v1/routing/config") {
      return ok({ ...routingConfigFixture(), ...(req.body as object) })
    }
    return err(404, { detail: "unhandled test route" })
  })
  render(
    <FreeSearchProvider>
      <SettingsView />
    </FreeSearchProvider>
  )
  return stub
}

async function waitForProviders() {
  await waitFor(() => {
    expect(screen.getByText("Brave Search", { exact: true })).toBeInTheDocument()
  })
}

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

describe("SettingsView (live backend)", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("renders exactly Providers, Keys, and Failover tabs", async () => {
    renderSettings()
    await waitForProviders()

    expect(screen.getAllByRole("tab")).toHaveLength(3)
    for (const label of ["Providers", "Keys", "Failover"]) {
      expect(screen.getByRole("tab", { name: new RegExp(`^${label}$`) })).toBeInTheDocument()
    }
    expect(screen.queryByRole("tab", { name: /^Cache$/ })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /add provider/i })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /remove|delete provider/i })).not.toBeInTheDocument()
  })

  it("shows all backend providers with priorities and no add/remove actions", async () => {
    renderSettings()
    await waitForProviders()

    for (const provider of seedProviderNames) {
      expect(screen.getByText(provider, { exact: true })).toBeInTheDocument()
    }
    for (let priority = 1; priority <= seedProviderNames.length; priority += 1) {
      expect(screen.getByText(`P${priority}`, { exact: true })).toBeInTheDocument()
    }
    expect(screen.getAllByRole("switch")).toHaveLength(7)
  })

  it("labels every global switch with its provider name", async () => {
    renderSettings()
    await waitForProviders()

    for (const provider of seedProviderNames) {
      expect(
        screen.getByRole("switch", { name: `${provider} global routing` })
      ).toBeInTheDocument()
    }
  })

  it("persists a global toggle via PATCH and disables the switch while pending", async () => {
    const user = userEvent.setup()
    const gate = deferred<Response>()
    const stub = renderSettings()
    await waitForProviders()
    patchGate = gate.promise

    const braveSwitch = screen.getByRole("switch", { name: "Brave Search global routing" })
    await user.click(braveSwitch)

    // Pending: control is disabled until the 200 lands
    await waitFor(() => {
      expect(
        screen.getByRole("switch", { name: "Brave Search global routing" })
      ).toBeDisabled()
    })

    gate.resolve(ok({ ...allProvidersFixture()[0], enabled: false }))
    await waitFor(() => {
      expect(
        screen.getByRole("switch", { name: "Brave Search global routing" })
      ).toHaveAttribute("aria-checked", "false")
    })
    const patches = stub.requestsTo("/api/v1/providers/brave")
    expect(patches).toHaveLength(1)
    expect(patches[0].body).toEqual({ enabled: false })
  })

  it("keeps operation segments local-only and capability-gated", async () => {
    const user = userEvent.setup()
    const stub = renderSettings()
    await waitForProviders()

    const row = findProviderRow("Brave Search")
    const searchOperation = within(row).getByText("Search", { exact: true }).parentElement!
    await user.click(within(searchOperation).getByRole("button", { name: /^Off$/ }))
    expect(
      within(searchOperation).getByRole("button", { name: /^Off$/ })
    ).toHaveAttribute("aria-pressed", "true")
    // Local-only: no PATCH for per-operation flips
    expect(
      stub.requests.filter((r) => r.method === "PATCH")
    ).toHaveLength(0)
    // Brave is search-only: fetch shows the unsupported guard, never a switch
    expect(within(row).getByText("Not supported", { exact: true })).toBeInTheDocument()
  })

  it("labels every key input with its provider name and disables Save on blank", async () => {
    const user = userEvent.setup()
    renderSettings()
    await waitForProviders()
    await user.click(screen.getByRole("tab", { name: /^Keys$/ }))

    for (const provider of seedProviderNames) {
      expect(
        screen.getByRole("textbox", { name: `${provider} API key` })
      ).toBeInTheDocument()
    }
    const card = findKeyCard("You.com")
    expect(within(card).getByRole("button", { name: /^Save$/ })).toBeDisabled()
  })

  it("saves a key with the SERVER fingerprint and clears the write-only input", async () => {
    const user = userEvent.setup()
    const stub = renderSettings()
    await waitForProviders()
    await user.click(screen.getByRole("tab", { name: /^Keys$/ }))

    const card = findKeyCard("You.com")
    const input = card.querySelector('input[type="password"]') as HTMLInputElement
    await user.type(input, "yc_live_secret_key_6789")
    await user.click(within(card).getByRole("button", { name: /^Save$/ }))

    // Fingerprint comes from the backend response — never locally computed
    await waitFor(() => {
      expect(within(card).getByText("YOU_••••••••a1b2", { exact: true })).toBeInTheDocument()
    })
    expect(within(card).getByText("Stored", { exact: true })).toBeInTheDocument()
    expect(input).toHaveValue("")
    expect(document.body.textContent).not.toContain("yc_live_secret_key_6789")
    const puts = stub.requestsTo("/api/v1/providers/you/secret")
    expect(puts).toHaveLength(1)
    expect(puts[0].body).toEqual({ key: "yc_live_secret_key_6789" })
  })

  it("exposes a Delete secret button per key card", async () => {
    const user = userEvent.setup()
    const stub = renderSettings()
    await waitForProviders()
    await user.click(screen.getByRole("tab", { name: /^Keys$/ }))

    const card = findKeyCard("Tavily")
    const deleteButton = within(card).getByRole("button", { name: /^Delete/ })
    await user.click(deleteButton)

    await waitFor(() => {
      expect(within(card).getByText("Missing", { exact: true })).toBeInTheDocument()
    })
    const deletes = stub.requestsTo("/api/v1/providers/tavily/secret")
    expect(deletes).toHaveLength(1)
    expect(deletes[0].method).toBe("DELETE")
  })

  it("surfaces an environment/dotenv shadowing note for shadowed keys", async () => {
    const user = userEvent.setup()
    secretSource = "keyring"
    renderSettings()
    await waitForProviders()
    await user.click(screen.getByRole("tab", { name: /^Keys$/ }))

    secretSource = "environment"
    const card = findKeyCard("Exa")
    const input = card.querySelector('input[type="password"]') as HTMLInputElement
    await user.type(input, "exa-live-key")
    await user.click(within(card).getByRole("button", { name: /^Save$/ }))

    await waitFor(() => {
      expect(card.textContent).toMatch(/environment|dotenv|shadow/i)
    })
  })

  it("renders the write-only key vault with no reveal actions", async () => {
    const user = userEvent.setup()
    renderSettings()
    await waitForProviders()
    await user.click(screen.getByRole("tab", { name: /^Keys$/ }))

    expect(screen.getAllByText(/••••••••/).length).toBeGreaterThan(0)
    const body = document.body.textContent ?? ""
    for (const forbidden of ["Copy", "Burn", "Reveal", "shown once"]) {
      expect(body).not.toContain(forbidden)
    }
  })

  it("renders failover switches with descriptions and honest timeout copy", async () => {
    const user = userEvent.setup()
    renderSettings()
    await waitForProviders()
    await user.click(screen.getByRole("tab", { name: /^Failover$/ }))

    for (const label of [
      "Fallback chaining",
      "Failover on rate limit (429)",
      "Failover on timeout",
      "Failover on server error (5xx)",
    ]) {
      expect(screen.getByText(label, { exact: true })).toBeInTheDocument()
    }
    expect(screen.getByText("Cascade depth", { exact: true })).toBeInTheDocument()
    // Honest copy: the invented per-hop budget is gone everywhere in Settings
    expect(screen.queryByText("3,000 ms", { exact: true })).not.toBeInTheDocument()
  })

  it("describes failover as single-attempt dispatch with session-only sub-switches", async () => {
    const user = userEvent.setup()
    renderSettings()
    await waitForProviders()
    await user.click(screen.getByRole("tab", { name: /^Failover$/ }))

    // The master switch must disclose single-attempt dispatch (the backend
    // never retries across providers on its own).
    expect(document.body.textContent).toMatch(/single attempt|no cross-provider retry/i)
    // At least one per-condition sub-switch is session-only (not enforced
    // by the backend).
    expect(screen.getByText(/session-only|not enforced/i)).toBeInTheDocument()
  })

  it("masks a draft key as opaque bullets with no prefix/suffix leak (pre-save)", async () => {
    const user = userEvent.setup()
    renderSettings()
    await waitForProviders()
    await user.click(screen.getByRole("tab", { name: /^Keys$/ }))

    const card = findKeyCard("You.com")
    const input = card.querySelector('input[type="password"]') as HTMLInputElement
    await user.type(input, "yc_live_secret_key_6789")

    // Before save the card shows opaque bullets only: neither the typed
    // prefix nor the last-4 suffix may appear in the card's rendered text.
    expect(within(card).getByText(/••••••••/)).toBeInTheDocument()
    const text = card.textContent ?? ""
    expect(text).not.toContain("yc_l")
    expect(text).not.toContain("6789")
  })
})
