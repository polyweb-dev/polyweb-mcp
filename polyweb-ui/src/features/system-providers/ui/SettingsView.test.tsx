import React from "react"
import { describe, expect, it, afterEach, vi } from "vitest"
import { render, screen, within, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router"
import { PolywebProvider } from "@/context/PolywebContext"
import { ProjectsProvider } from "@/domains/projects"
import { HARNESS_ACCOUNT, installWorkspaceStub } from "@/test/workspaceHarness"
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
      return ok({ ...base, enable_mask: enableMask, enabled: (enableMask & 1) !== 0 })
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
    <MemoryRouter>
      <PolywebProvider accountId={ADMIN_ACCOUNT_ID} canReadControls canEditControls>
        <SettingsView />
        <ToastContainer />
      </PolywebProvider>
    </MemoryRouter>
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

  it("without key management shows only the Providers view: no tabs, no Failover tab, no secret input", async () => {
    renderSettings()
    await waitForProviders()

    expect(screen.queryAllByRole("tab")).toHaveLength(0)
    expect(screen.queryByRole("tab", { name: /^Keys$/ })).not.toBeInTheDocument()
    expect(screen.queryByRole("tab", { name: /^Failover$/ })).not.toBeInTheDocument()
    expect(document.body.querySelector('input[type="password"]')).toBeNull()
    expect(screen.queryByRole("tab", { name: /^Cache$/ })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /add provider/i })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /remove|delete provider/i })).not.toBeInTheDocument()
  })

  it("shows all backend providers without order or add/remove actions", async () => {
    renderSettings()
    await waitForProviders()

    for (const provider of seedProviderNames) {
      expect(screen.getByText(provider, { exact: true })).toBeInTheDocument()
    }
    const table = screen.getByRole("table")
    expect(within(table).queryByRole("columnheader", { name: "Priority" })).not.toBeInTheDocument()
    expect(within(table).getByRole("columnheader", { name: "Cost per call" })).toBeInTheDocument()
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
    // Brave is search-only: fetch reads as unavailable, not as a switch
    expect(within(row).queryByRole("switch", { name: /fetch routing/ })).toBeNull()
    expect(within(row).getByText("Brave Search does not support fetch")).toBeInTheDocument()
  })






  it("renders only the persisted fallback controls under the provider table", async () => {
    renderSettings()
    await waitForProviders()

    const section = screen.getByRole("heading", { name: "When a provider fails" }).closest("section") as HTMLElement
    expect(within(section).getByRole("switch", { name: "Fallback" })).toHaveAttribute("aria-checked", "true")
    expect(within(section).getByText("Max attempts", { exact: true })).toBeInTheDocument()
    expect(within(section).getByText("3", { exact: true })).toBeInTheDocument()
    for (const removed of [
      "Failover on rate limit (429)",
      "Failover on timeout",
      "Failover on server error (5xx)",
      "Cascade depth",
      "Timeout budget",
    ]) {
      expect(screen.queryByText(removed)).not.toBeInTheDocument()
    }
    // Honest copy: the invented per-hop budget is gone everywhere in Settings
    expect(screen.queryByText("3,000 ms", { exact: true })).not.toBeInTheDocument()
  })

  it("shows no developer notes about session-only or unexposed settings", async () => {
    renderSettings()
    await waitForProviders()

    expect(document.body.textContent).not.toMatch(/session-only|not enforced|not exposed|persisted for backend/i)
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
      <MemoryRouter>
        <PolywebProvider accountId={DEVELOPER_ACCOUNT_ID} canReadControls canEditControls={false}>
          <SettingsView />
          <ToastContainer />
        </PolywebProvider>
      </MemoryRouter>
    )
    return stub
  }

  it("shows no Keys tab or key vault, keeps the Providers view, and sends no writes", async () => {
    const stub = renderDeveloperSettings()
    await waitForProviders()

    // Read-only markers present: the Providers view only, so no tab list.
    expect(screen.queryAllByRole("tab")).toHaveLength(0)
    expect(screen.getByRole("heading", { level: 2, name: "Providers" })).toBeInTheDocument()
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

describe("SettingsView with key management", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function renderWithKeys(entry: string) {
    const stub = installWorkspaceStub((req) => {
      if (req.url === "/api/v1/providers" && req.method === "GET") return ok(allProvidersFixture())
      if (req.url === "/api/v1/routing/config" && req.method === "GET") return ok(routingConfigFixture())
      if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
      if (req.url === "/api/v1/system/credentials" && req.method === "GET") return ok([])
      return err(404, { detail: "unhandled test route" })
    })
    render(
      <MemoryRouter initialEntries={[entry]}>
        <ProjectsProvider accountId={HARNESS_ACCOUNT}>
          <PolywebProvider accountId={HARNESS_ACCOUNT} canReadControls canEditControls>
            <SettingsView />
          </PolywebProvider>
        </ProjectsProvider>
      </MemoryRouter>
    )
    return stub
  }

  it("shows the provider catalog without a Keys tab", async () => {
    renderWithKeys("/system/providers")
    await waitForProviders()
    expect(screen.queryAllByRole("tab")).toHaveLength(0)
    expect(screen.queryByRole("tab", { name: "Failover" })).not.toBeInTheDocument()
    expect(screen.queryByRole("tab", { name: "Credentials" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Add key" })).toBeNull()
  })

  it("keeps the catalog visible for the former ?tab=credentials", async () => {
    const stub = renderWithKeys("/system/providers?tab=credentials")
    await waitForProviders()
    expect(screen.queryByRole("heading", { name: "System keys" })).not.toBeInTheDocument()
    expect(stub.requestsTo("/api/v1/system/credentials")).toHaveLength(0)
  })

  it("keeps the fallback section visible for the former ?tab=failover", async () => {
    renderWithKeys("/system/providers?tab=failover")
    expect(await screen.findByRole("heading", { name: "When a provider fails" })).toBeInTheDocument()
  })

  it("keeps the catalog visible for the former ?tab=keys", async () => {
    const stub = renderWithKeys("/system/providers?tab=keys")
    await waitForProviders()
    expect(screen.queryByRole("button", { name: "Add key" })).not.toBeInTheDocument()
    expect(stub.requestsTo("/api/v1/system/credentials")).toHaveLength(0)
  })

  it("retains the provider controls without a tab list", async () => {
    renderWithKeys("/system/providers?tab=providers")
    await waitForProviders()
    expect(screen.getByRole("switch", { name: "Brave Search global routing" })).toBeInTheDocument()
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument()
  })
})
