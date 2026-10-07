import React from "react"
import { describe, it, expect, afterEach, vi } from "vitest"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { QuotaAnalytics } from "./QuotaAnalytics"
import { installFetchStub, ok, err } from "@/test/fetchMock"
import { ADMIN_ACCOUNT_ID, DEVELOPER_ACCOUNT_ID } from "@/test/authFixtures"
import {
  allProvidersFixture,
  routingConfigFixture,
  dashboardFixture,
  canonicalQuotasFixture,
} from "@/test/backendFixtures"

/**
 * Manual billing entry overlay: Brave always offers Set budget, Exa/Parallel/Tinyfish
 * offer it while no vendor budget is configured, and a saved window renders
 * as an ESTIMATED overlay line without rewriting the throttle headline.
 */
function renderWithManualStub(latestQuota = canonicalQuotasFixture()) {
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
      return ok(dashboardFixture({ latest_quota: latestQuota }))
    }
    return err(404, { detail: "unhandled test route" })
  })
  render(
    <FreeSearchProvider accountId={ADMIN_ACCOUNT_ID} canReadControls canEditControls>
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

  it("offers Tinyfish manual entry while its monthly budget is unconfigured", async () => {
    const user = userEvent.setup()
    const stub = renderWithManualStub()
    const row = (await screen.findByText("Tinyfish quota", { exact: true })).closest("tr")!
    expect(row).toHaveTextContent("Budget not configured")
    expect(row).toHaveTextContent("Monthly")
    expect(screen.getByTestId("manual-quota-open-tinyfish")).toHaveTextContent("Set budget")
    await user.click(screen.getByTestId("manual-quota-open-tinyfish"))
    const dialog = await screen.findByRole("dialog")
    expect(dialog).toHaveTextContent("Set budget — Tinyfish")
    expect(stub.requestsTo("/api/v1/providers/tinyfish/manual-quota").map((request) => request.method)).toContain("GET")
  })

  it("hides Tinyfish manual entry when a finite vendor quota exists", async () => {
    renderWithManualStub([...canonicalQuotasFixture(), {
      provider: "tinyfish",
      source: "authoritative",
      observed_at: "2026-09-06T12:00:00Z",
      remaining: "750",
      limit: "1000",
      remaining_percent: "75",
      unit_kind: "REQUEST",
      reset_at: null,
    }])
    const row = (await screen.findByText("Tinyfish quota", { exact: true })).closest("tr")!
    expect(row).toHaveTextContent("75% remaining")
    expect(row).toHaveTextContent("750/1000 requests")
    expect(screen.queryByTestId("manual-quota-open-tinyfish")).toBeNull()
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
      name: /estimated remaining from Manual Entry/i,
    })
    expect(bar).toHaveAttribute("aria-valuenow", "82.4")
    expect(bar.firstElementChild).toHaveStyle({ width: "82.4%" })
    expect(estimate.closest("tr")).toHaveTextContent(/Manual Entry \w{3} 1–\w{3} 30/)

    // Consolidated row: the manual estimate leads and the vendor demotes.
    const row = screen.getByText("Brave Search quota", { exact: true }).closest("tr")!
    expect(row.querySelector("time")).toHaveAttribute("datetime", "2026-09-30")
    expect(row.children[2]).not.toHaveTextContent(/manual entry/i)
    expect(row.children[4]).toHaveTextContent(/manual entry/i)
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

/**
 * Developer role (control read without control edit): the permitted manual
 * quota read stays visible, but no manual action button or modal and no
 * provider OAuth slot renders. The stub serves reads only.
 */
describe("QuotaAnalytics Developer read-only", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("shows quota reads with no manual actions and no OAuth slot (stub reads only)", async () => {
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
      if (req.url.startsWith("/dashboard")) {
        return ok(dashboardFixture({ latest_quota: canonicalQuotasFixture() }))
      }
      return err(404, { detail: "unhandled test route" })
    })
    render(
      <FreeSearchProvider
        accountId={DEVELOPER_ACCOUNT_ID}
        canReadControls
        canEditControls={false}
      >
        <QuotaAnalytics />
      </FreeSearchProvider>
    )

    // Permitted read: the quota rows render from the control reads.
    await waitFor(() => {
      expect(screen.getByText("Brave Search quota", { exact: true })).toBeInTheDocument()
    })
    expect(screen.getByText("Tinyfish quota", { exact: true })).toBeInTheDocument()
    expect(
      stub.requestsTo("/api/v1/providers/tinyfish/manual-quota").map((request) => request.method)
    ).toContain("GET")

    // No manual action buttons or modals without control edit access.
    expect(screen.queryByTestId("manual-quota-open-brave")).toBeNull()
    expect(screen.queryByTestId("manual-quota-open-parallel")).toBeNull()
    expect(screen.queryByTestId("manual-quota-open-tinyfish")).toBeNull()
    expect(screen.queryByRole("dialog")).toBeNull()

    // No provider OAuth slot without control edit access.
    expect(screen.queryByTestId("oauth-device-open-parallel")).toBeNull()
    expect(screen.queryByTestId("oauth-device-disconnect")).toBeNull()

    // Stub reads only: every request is a GET.
    expect(stub.requests.length).toBeGreaterThan(0)
    expect(stub.requests.every((request) => request.method === "GET")).toBe(true)
  })
})
