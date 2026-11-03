import React from "react"
import { describe, expect, it, afterEach, vi } from "vitest"
import { render, screen, within, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { ADMIN_ACCOUNT_ID, DEVELOPER_ACCOUNT_ID } from "@/test/authFixtures"
import { ToastContainer } from "@/components/common/ToastContainer"
import { SettingsView } from "./SettingsView"
import { installFetchStub, ok, err, deferred, type FetchStub } from "@/test/fetchMock"
import {
  allProvidersFixture,
  routingConfigFixture,
  dashboardFixture,
} from "@/test/backendFixtures"

/**
 * RED update: every control is async against the live backend (mocked fetch).
 * Global switches PATCH with pending/disabled states + error toasts,
 * per-operation switches stay local-only and capability-gated, and the
 * invented "3,000 ms" copy is gone. The global key vault is gone (U3):
 * provider secrets live on credential instances, so no tab writes a secret.
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

let patchGate: Promise<Response> | null = null

function renderSettings(): FetchStub {
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
      const backendId = req.url.split("/").at(-1) ?? "unknown"
      const wire = allProvidersFixture().find((p) => p.provider_id === backendId)
      const base = { ...(wire ?? allProvidersFixture()[0]) } as Record<string, unknown> & {
        enable_mask: number
        priority: number
      }
      const patch = ((req.body as Record<string, unknown>) ?? {}) as Record<string, unknown>
      let enableMask = base.enable_mask
      if (typeof patch.enable_mask === "number") enableMask = patch.enable_mask
      else {
        if (patch.enabled === true) enableMask |= 1
        if (patch.enabled === false) enableMask &= ~1
        if (patch.search_enabled === true) enableMask |= 2
        if (patch.search_enabled === false) enableMask &= ~2
        if (patch.fetch_enabled === true) enableMask |= 4
        if (patch.fetch_enabled === false) enableMask &= ~4
      }
      const priority = typeof patch.priority === "number" ? patch.priority : base.priority
      return ok({ ...base, enable_mask: enableMask, enabled: (enableMask & 1) !== 0, priority })
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
    <FreeSearchProvider accountId={ADMIN_ACCOUNT_ID} canReadControls canEditControls>
      <SettingsView />
      <ToastContainer />
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
  const tr = providerName.closest("tr")
  if (tr) return tr

  throw new Error(`Provider registry row not found for ${provider}`)
}

describe("SettingsView (live backend)", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("renders exactly Providers and Failover tabs, with no Keys tab or secret input", async () => {
    renderSettings()
    await waitForProviders()

    expect(screen.getAllByRole("tab")).toHaveLength(2)
    expect(screen.queryByRole("tab", { name: /^Keys$/ })).not.toBeInTheDocument()
    expect(document.body.querySelector('input[type="password"]')).toBeNull()
    for (const label of ["Providers", "Failover"]) {
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
    for (const provider of seedProviderNames) {
      expect(
        screen.getByRole("switch", { name: `${provider} global routing` })
      ).toBeInTheDocument()
    }
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

    gate.resolve(ok({ ...allProvidersFixture()[0], enable_mask: 6, enabled: false }))
    await waitFor(() => {
      expect(
        screen.getByRole("switch", { name: "Brave Search global routing" })
      ).toHaveAttribute("aria-checked", "false")
    })
    const patches = stub.requestsTo("/api/v1/providers/brave")
    expect(patches).toHaveLength(1)
    expect(patches[0].body).toEqual({ enabled: false })
  })

  it("persists operation switches via durable PATCH and capability-gates unsupported tools", async () => {
    const user = userEvent.setup()
    const stub = renderSettings()
    await waitForProviders()

    const row = findProviderRow("Brave Search")
    const searchSwitch = within(row).getByRole("switch", { name: "Brave Search search routing" })
    expect(searchSwitch).toHaveAttribute("aria-checked", "true")
    await user.click(searchSwitch)
    await waitFor(() => {
      expect(
        within(findProviderRow("Brave Search")).getByRole("switch", {
          name: "Brave Search search routing",
        }),
      ).toHaveAttribute("aria-checked", "false")
    })
    const searchPatches = stub.requestsTo("/api/v1/providers/brave")
    expect(searchPatches).toHaveLength(1)
    expect(searchPatches[0].body).toEqual({ search_enabled: false })
    // Brave is search-only: fetch shows the disabled switch
    const fetchSwitch = within(row).getByRole("switch", { name: "Brave Search fetch routing (not supported)" })
    expect(fetchSwitch).toBeDisabled()
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

})

describe("SettingsView Developer read-only (canReadControls, no edit)", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function renderDeveloperSettings(): FetchStub {
    const stub = installFetchStub((req) => {
      if (req.url === "/api/v1/providers" && req.method === "GET") {
        return ok(allProvidersFixture())
      }
      if (req.url === "/api/v1/routing/config" && req.method === "GET") {
        return ok(routingConfigFixture())
      }
      if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
      return err(404, { detail: "unhandled test route" })
    })
    render(
      <FreeSearchProvider accountId={DEVELOPER_ACCOUNT_ID} canReadControls canEditControls={false}>
        <SettingsView />
        <ToastContainer />
      </FreeSearchProvider>
    )
    return stub
  }

  it("shows no Keys tab or key vault, keeps Providers/Failover, and sends no writes", async () => {
    const stub = renderDeveloperSettings()
    await waitForProviders()

    // Read-only markers present: exactly Providers + Failover tabs.
    expect(screen.getAllByRole("tab")).toHaveLength(2)
    expect(screen.getByRole("tab", { name: /^Providers$/ })).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: /^Failover$/ })).toBeInTheDocument()
    // Mutation affordances absent: no Keys tab, so the vault never mounts.
    expect(screen.queryByRole("tab", { name: /^Keys$/ })).not.toBeInTheDocument()
    expect(screen.queryByRole("heading", { name: "Key vault" })).not.toBeInTheDocument()
    expect(screen.queryByRole("textbox", { name: /API key/ })).not.toBeInTheDocument()
    expect(document.body.querySelector('input[type="password"]')).toBeNull()
    // Zero backend writes beyond the stubbed reads.
    expect(
      stub.requests.filter((r) => r.method === "PATCH" || r.method === "PUT" || r.method === "POST")
    ).toHaveLength(0)
  })
})
