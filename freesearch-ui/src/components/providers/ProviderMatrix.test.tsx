import React from "react"
import { describe, it, expect, afterEach, vi } from "vitest"
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { ProviderMatrix } from "./ProviderMatrix"
import { installFetchStub, ok, err } from "@/test/fetchMock"
import {
  allProvidersFixture,
  routingConfigFixture,
  dashboardFixture,
  type WireProviderStatus,
} from "@/test/backendFixtures"

/**
 * RED (new file): the matrix splits breaker controls — Trip is local-only
 * (ZERO fetch) while Reset POSTs
 * /api/v1/providers/{backendId}/circuit-breaker/reset. Null p95 latency
 * renders "—".
 */
function renderWithBackend(providers: WireProviderStatus[]) {
  const stub = installFetchStub((req) => {
    if (req.url === "/api/v1/providers" && req.method === "GET") return ok(providers)
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
    if (req.method === "POST" && req.url.endsWith("/circuit-breaker/reset")) {
      return ok({ provider: "x", state: "closed", updated_at: "2026-09-06T10:06:00Z" })
    }
    return err(404, { detail: "unhandled test route" })
  })
  render(
    <FreeSearchProvider>
      <ProviderMatrix />
    </FreeSearchProvider>
  )
  return stub
}

function rowFor(providerName: string): HTMLElement {
  const name = screen.getByText(providerName, { exact: true })
  let current: HTMLElement | null = name.parentElement
  while (current && current !== document.body) {
    if (within(current).queryByRole("button", { name: /^(Trip|Reset)$/ })) {
      return current
    }
    current = current.parentElement
  }
  throw new Error(`Matrix row not found for ${providerName}`)
}

describe("ProviderMatrix (live backend)", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("trips a breaker locally with ZERO fetch", async () => {
    const stub = renderWithBackend(allProvidersFixture())
    await waitFor(() => {
      expect(screen.getByText("Brave Search", { exact: true })).toBeInTheDocument()
    })

    const callsBefore = stub.requests.length
    fireEvent.click(within(rowFor("Brave Search")).getByRole("button", { name: "Trip" }))

    await waitFor(() => {
      expect(
        within(rowFor("Brave Search")).getByRole("button", { name: "Reset" })
      ).toBeInTheDocument()
    })
    expect(stub.requests.length).toBe(callsBefore)
  })

  it("resets a breaker via POST .../circuit-breaker/reset", async () => {
    const providers = allProvidersFixture().map((p) =>
      p.provider_id === "brave"
        ? { ...p, circuit_breaker: { state: "open", updated_at: "2026-09-06T00:00:00Z" } }
        : p
    )
    const stub = renderWithBackend(providers as WireProviderStatus[])
    await waitFor(() => {
      expect(
        within(rowFor("Brave Search")).getByRole("button", { name: "Reset" })
      ).toBeInTheDocument()
    })

    fireEvent.click(within(rowFor("Brave Search")).getByRole("button", { name: "Reset" }))

    await waitFor(() => {
      const resets = stub.requestsTo("/api/v1/providers/brave/circuit-breaker/reset")
      expect(resets).toHaveLength(1)
      expect(resets[0].method).toBe("POST")
    })
  })

  it("renders null p95 latency as '—' instead of a number", async () => {
    const providers = allProvidersFixture().map((p) =>
      p.provider_id === "exa" ? { ...p, latency_p95_ms: null } : p
    )
    renderWithBackend(providers as WireProviderStatus[])
    await waitFor(() => {
      expect(screen.getByText("Exa", { exact: true })).toBeInTheDocument()
    })

    const rowText = rowFor("Exa").textContent ?? ""
    expect(rowText).toContain("—")
    expect(rowText).not.toContain("null")
    expect(rowText).not.toContain("NaN")
  })

  it("renders the persistent providersError when the providers route fails", async () => {
    installFetchStub((req) => {
      if (req.url === "/api/v1/providers" && req.method === "GET") {
        return err(500, { detail: "db down" })
      }
      if (req.url === "/api/v1/routing/config" && req.method === "GET") {
        return ok(routingConfigFixture())
      }
      if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
      return err(404, { detail: "unhandled test route" })
    })
    render(
      <FreeSearchProvider>
        <ProviderMatrix />
      </FreeSearchProvider>
    )

    // After loading settles the authoritative error stays visible in the view.
    await waitFor(
      () => {
        expect(screen.getByText(/db down/i)).toBeInTheDocument()
      },
      { timeout: 5000 }
    )
  })

  it("excludes degraded providers from the healthy count", async () => {
    const providers = allProvidersFixture().map((p) =>
      p.provider_id === "tavily" ? { ...p, health: "degraded" as const } : p
    )
    renderWithBackend(providers as WireProviderStatus[])
    await waitFor(() => {
      expect(screen.getByText("Tavily", { exact: true })).toBeInTheDocument()
    })

    const healthLabel = screen.getByText("Health status", { exact: true })
    const cardText = healthLabel.parentElement?.textContent ?? ""
    expect(cardText).toMatch(/6\s*healthy/)
    expect(cardText).not.toMatch(/7\s*healthy/)
  })
})
