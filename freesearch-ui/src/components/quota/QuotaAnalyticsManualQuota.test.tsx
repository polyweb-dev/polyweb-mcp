import React from "react"
import { describe, it, expect, afterEach, vi } from "vitest"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { QuotaAnalytics } from "./QuotaAnalytics"
import { installFetchStub, ok, err } from "@/test/fetchMock"
import {
  allProvidersFixture,
  routingConfigFixture,
  dashboardFixture,
  canonicalQuotasFixture,
} from "@/test/backendFixtures"

/**
 * Manual billing entry overlay: Brave always offers Set budget, Exa/Parallel
 * offer it while no vendor budget is configured, and a saved window renders
 * as an ESTIMATED overlay line without rewriting the throttle headline.
 */
function renderWithManualStub() {
  const stub = installFetchStub((req) => {
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(allProvidersFixture())
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url.endsWith("/manual-quota") && req.method === "GET") {
      return err(404, { detail: "no manual quota configured" })
    }
    if (req.url.endsWith("/manual-quota") && req.method === "PUT") {
      const body = req.body as Record<string, string>
      return ok({ provider: "brave", ...body, updated_at: "2026-09-06T12:00:00Z" })
    }
    if (req.url.startsWith("/dashboard")) {
      return ok(dashboardFixture({ latest_quota: canonicalQuotasFixture() }))
    }
    return err(404, { detail: "unhandled test route" })
  })
  render(
    <FreeSearchProvider>
      <QuotaAnalytics />
    </FreeSearchProvider>
  )
  return stub
}

describe("QuotaAnalytics manual billing entry", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("offers Set budget on Brave always and on unbudgeted Parallel, never on Tavily", async () => {
    renderWithManualStub()
    await waitFor(() => {
      expect(screen.getByText("Brave Search quota", { exact: true })).toBeInTheDocument()
    })
    expect(screen.getByTestId("manual-quota-open-brave")).toHaveTextContent("Set budget")
    expect(screen.getByTestId("manual-quota-open-parallel")).toHaveTextContent("Set budget")
    expect(screen.queryByTestId("manual-quota-open-tavily")).toBeNull()
  })

  it("saves a Brave window and shows an estimated overlay beside the observed headline", async () => {
    const user = userEvent.setup()
    const stub = renderWithManualStub()
    await waitFor(() => {
      expect(screen.getByTestId("manual-quota-open-brave")).toBeInTheDocument()
    })

    await user.click(screen.getByTestId("manual-quota-open-brave"))
    fireEvent.change(screen.getByTestId("manual-quota-start"), {
      target: { value: "2026-09-01" },
    })
    fireEvent.change(screen.getByTestId("manual-quota-end"), {
      target: { value: "2026-09-30" },
    })
    fireEvent.change(screen.getByTestId("manual-quota-allowance"), {
      target: { value: "5.00" },
    })
    fireEvent.change(screen.getByTestId("manual-quota-usage"), {
      target: { value: "0.88" },
    })
    await user.click(screen.getByTestId("manual-quota-save"))

    await waitFor(() => {
      expect(screen.getByTestId("manual-quota-estimate-brave")).toBeInTheDocument()
    })
    const puts = stub.requestsTo("/api/v1/providers/brave/manual-quota")
    expect(puts.map((request) => request.method)).toContain("PUT")
    expect(puts.find((request) => request.method === "PUT")?.body).toEqual({
      billing_start: "2026-09-01",
      billing_end: "2026-09-30",
      allowance: "5.00",
      current_usage: "0.88",
    })

    // Estimated overlay: Decimal-safe 82.4% with the billing window.
    const estimate = screen.getByTestId("manual-quota-estimate-brave")
    expect(estimate).toHaveTextContent("82.4% remaining")
    const bar = within(estimate).getByRole("progressbar", {
      name: /estimated remaining from manual entry/i,
    })
    expect(bar).toHaveAttribute("aria-valuenow", "82.4")
    expect(bar.firstElementChild).toHaveStyle({ width: "82.4%" })
    expect(estimate).toHaveTextContent(/manual entry \w{3} 1–\w{3} 30/)

    // Consolidated row: the manual estimate leads and the vendor demotes.
    const row = screen.getByText("Brave Search quota", { exact: true }).parentElement!
    expect(row.textContent).toContain("observed")
    expect(
      row.querySelector('[data-testid="quota-remaining-percent-brave"]')
    ).toBeNull()
    expect(row.textContent).toContain("estimated")
    expect(row.textContent).toContain("Vendor: 950/1000 requests")
    expect(row.textContent).not.toContain("Limit unavailable")

    // Button flips to Update usage for the next edit.
    expect(screen.getByTestId("manual-quota-open-brave")).toHaveTextContent("Update usage")
  })
})