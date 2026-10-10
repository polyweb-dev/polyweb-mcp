import React from "react"
import { describe, it, expect, afterEach, vi } from "vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { QuotaAnalytics } from "./QuotaAnalytics"
import { installFetchStub, ok, err } from "@/test/fetchMock"
import { ADMIN_ACCOUNT_ID, DEVELOPER_ACCOUNT_ID } from "@/test/authFixtures"
import {
  allProvidersFixture,
  routingConfigFixture,
  dashboardFixture,
  type WireDashboardQuota,
} from "@/test/backendFixtures"

/**
 * UI7 manual entry through the shell: card buttons read
 * "Provider Balance", the dialog keeps native-anchor transport, and the
 * card USD path translates balance to usage (see useQuotaForm tests
 * for the 5.00/4.12 to 0.88 contract). Covers UI7-07.
 *
 * NUDGE-5: the Provider actions section left the page, and Brave is no
 * longer manual-eligible (its vendor snapshot reports remaining 999 of
 * limit 1000). Manual assertions anchor on the Exa/Tinyfish cards, and
 * Brave keeps no Provider Balance control.
 */

/** One card-level limit entry with no vendor funds, so the card mounts. */
function limitEntry(provider: string): Record<string, unknown> {
  const profile = {
    reference_usd_per_crd: "0.001",
    native_usd_per_unit: "1",
    cost_basis: "priced_native_use",
    price_version: "v2026-09",
    source: "documented",
    estimated: false,
  }
  return {
    provider,
    active_auth_mode: "keyed",
    auths: [
      {
        auth_mode: "keyed",
        transport_available: true,
        search: {
          provider,
          operation: "search",
          auth_mode: "keyed",
          supported: true,
          transport_available: true,
          rate: null,
          budget: null,
          native_pool_id: null,
          conversion_profile: profile,
          plan_name: null,
          usage_url: null,
          version: 1,
        },
        fetch: {
          provider,
          operation: "fetch",
          auth_mode: "keyed",
          supported: false,
          transport_available: false,
          rate: null,
          budget: null,
          native_pool_id: null,
          conversion_profile: { ...profile, native_usd_per_unit: null },
          plan_name: null,
          usage_url: null,
          version: 1,
        },
        free_tiers: [],
        paid_tiers: [],
        unknown_tiers: [],
        tier_split_known: true,
        aggregate_pool: null,
        crd_views: [],
        rate_progress: [],
        grants: null,
        detail: null,
      },
    ],
    documented_keyless_operations: [],
    version: 1,
    generated_at: "2026-09-06T10:05:00Z",
  }
}

/**
 * Dashboard rows for the manual suite: Brave carries a vendor snapshot
 * (remaining 999 of limit 1000, so no manual entry), Exa and Parallel
 * carry null snapshots (eligible), and Tinyfish has no row (eligible).
 */
function manualQuotaRows(): WireDashboardQuota[] {
  return [
    {
      provider: "brave",
      source: "observed",
      observed_at: "2026-09-06T18:05:00Z",
      remaining: "999",
      limit: "1000",
      reset_at: "2026-10-01T00:00:00Z",
      unit_kind: "REQUEST",
      display_unit: "requests",
    },
    {
      provider: "exa",
      source: "estimated",
      observed_at: "2026-09-06T18:15:00Z",
      remaining: null,
      limit: null,
      reset_at: null,
      unit_kind: null,
      display_unit: null,
    },
    {
      provider: "parallel",
      source: "estimated",
      observed_at: "2026-09-06T18:20:00Z",
      remaining: null,
      limit: null,
      reset_at: null,
      unit_kind: "USD",
      display_unit: "USD",
    },
  ]
}

function renderWithManualStub(latestQuota = manualQuotaRows()) {
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
      const provider = req.url.split("/providers/")[1]?.split("/manual-quota")[0] ?? "unknown"
      const body = req.body as Record<string, string>
      return ok({ provider, ...body, updated_at: "2026-09-06T12:00:00Z" })
    }
    if (req.url.startsWith("/dashboard")) {
      return ok({
        ...(dashboardFixture({ latest_quota: latestQuota }) as unknown as Record<string, unknown>),
        provider_limits: [
          limitEntry("brave"),
          limitEntry("exa"),
          limitEntry("parallel"),
          limitEntry("tinyfish"),
        ],
      })
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

describe("QuotaAnalytics manual billing entry (UI7)", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("offers Provider Balance on Exa, Parallel, and Tinyfish, never on Brave or Tavily (UI7-07, NUDGE-5)", async () => {
    renderWithManualStub()
    await waitFor(() => {
      expect(screen.getByTestId("manual-quota-open-tinyfish")).toBeInTheDocument()
    })
    expect(screen.getByTestId("manual-quota-open-tinyfish")).toHaveTextContent("Provider Balance")
    expect(screen.getByTestId("manual-quota-open-exa")).toHaveTextContent("Provider Balance")
    expect(screen.getByTestId("manual-quota-open-parallel")).toHaveTextContent("Provider Balance")
    // NUDGE-5 lock: Brave reports a vendor budget, so its card keeps no entry control.
    expect(screen.getByRole("heading", { name: "Brave Search" })).toBeInTheDocument()
    expect(screen.queryByTestId("manual-quota-open-brave")).toBe(null)
    expect(screen.queryByTestId("manual-quota-open-tavily")).toBe(null)
    // NUDGE-5 lock: the Provider actions section left the page.
    expect(screen.queryByText("Provider actions")).toBe(null)
  })

  it("opens the native-anchor dialog for Tinyfish while its budget stays unconfigured (UI7-07)", async () => {
    const user = userEvent.setup()
    const stub = renderWithManualStub()
    await waitFor(() => {
      expect(screen.getByTestId("manual-quota-open-tinyfish")).toBeInTheDocument()
    })
    expect(screen.getByTestId("manual-quota-open-tinyfish")).toHaveTextContent("Provider Balance")
    await user.click(screen.getByTestId("manual-quota-open-tinyfish"))
    const dialog = await screen.findByRole("dialog")
    expect(dialog).toHaveTextContent("Tinyfish")
    expect(stub.requestsTo("/api/v1/providers/tinyfish/manual-quota").map((request) => request.method)).toContain("GET")
  })

  it("saves a Tinyfish window through the unchanged native payload (UI7-07)", async () => {
    const user = userEvent.setup()
    const stub = renderWithManualStub()
    await waitFor(() => {
      expect(screen.getByTestId("manual-quota-open-tinyfish")).toBeInTheDocument()
    })

    await user.click(screen.getByTestId("manual-quota-open-tinyfish"))
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
      const puts = stub.requestsTo("/api/v1/providers/tinyfish/manual-quota")
      expect(puts.map((request) => request.method)).toContain("PUT")
    })
    const puts = stub.requestsTo("/api/v1/providers/tinyfish/manual-quota")
    expect(puts.find((request) => request.method === "PUT")?.body).toEqual({
      billing_start: "2026-09-01",
      billing_end: "2026-09-30",
      allowance: "5.00",
      current_usage: "0.88",
    })
  })

  it("locks Provider Balance wording with its accessible meaning and no legacy labels (CARD-3)", async () => {
    renderWithManualStub()
    await waitFor(() => {
      expect(screen.getByTestId("manual-quota-open-tinyfish")).toBeInTheDocument()
    })
    expect(screen.getByTestId("manual-quota-open-tinyfish")).toHaveTextContent("Provider Balance")
    expect(
      screen.getByRole("button", {
        name: "Provider Balance for Tinyfish. Records the balance the vendor dashboard shows, as an estimate.",
      }),
    ).toBeInTheDocument()
    expect(screen.queryByText("Balance entry")).toBe(null)
    expect(screen.queryByText("Manual entry")).toBe(null)
  })

  it("shows no legacy overlay row and no action section on the new page (UI7-05, NUDGE-5)", async () => {
    renderWithManualStub()
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Tinyfish" })).toBeInTheDocument()
    })
    expect(screen.queryByText("Provider actions")).toBe(null)
    expect(screen.queryByText("Provider quota view")).toBe(null)
    expect(screen.queryByTestId("manual-quota-estimate-brave")).toBe(null)
    expect(screen.queryByTestId("manual-quota-open-brave")).toBe(null)
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
