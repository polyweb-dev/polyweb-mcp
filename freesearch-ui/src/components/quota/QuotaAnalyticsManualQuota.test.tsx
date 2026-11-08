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
        usd_views: [],
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
 * (remaining 999 of limit 1000, so no manual entry), Exa carries a null
 * snapshot (eligible), Parallel carries a null snapshot but stays ineligible
 * (its prepaid USD balance comes from the OAuth Account API, never a manual
 * seed), and Tinyfish has no row (eligible).
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
      return ok(null)
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

type User = ReturnType<typeof userEvent.setup>

/** The labels of one card's `…` menu; the menu closes again afterwards. */
async function menuLabels(user: User, providerName: string): Promise<string[]> {
  await user.click(screen.getByRole("button", { name: "Actions for " + providerName }))
  await screen.findByRole("button", { name: "Budget limit" })
  const labels = ["Set balance", "Budget limit", "Balance history"].filter(
    (label) => screen.queryByRole("button", { name: label }) !== null,
  )
  await user.keyboard("{Escape}")
  return labels
}

/** Open one dialog through the card `…` menu. */
async function openCardAction(user: User, providerName: string, label: string): Promise<void> {
  await user.click(screen.getByRole("button", { name: "Actions for " + providerName }))
  await user.click(await screen.findByRole("button", { name: label }))
}

async function waitForCard(providerName: string): Promise<void> {
  await waitFor(() => {
    expect(screen.getByRole("button", { name: "Actions for " + providerName })).toBeInTheDocument()
  })
}

describe("QuotaAnalytics manual billing entry (UI7)", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("offers Set balance on Exa and Tinyfish, never on Brave, Parallel, or Tavily (UI7-07, NUDGE-5)", async () => {
    const user = userEvent.setup()
    renderWithManualStub()
    await waitForCard("Tinyfish")
    expect(await menuLabels(user, "Tinyfish")).toContain("Set balance")
    expect(await menuLabels(user, "Exa")).toContain("Set balance")
    // Parallel stays out: its prepaid USD balance comes from the OAuth Account
    // API (AUTHORITATIVE snapshot), never from a manual seed.
    expect(await menuLabels(user, "Parallel")).not.toContain("Set balance")
    // NUDGE-5 lock: Brave reports a vendor budget, so its card keeps no entry control.
    expect(screen.getByRole("heading", { name: "Brave Search" })).toBeInTheDocument()
    expect(await menuLabels(user, "Brave Search")).not.toContain("Set balance")
    // NUDGE-5 lock: the Provider actions section left the page.
    expect(screen.queryByText("Provider actions")).toBe(null)
  })

  it("opens the native-anchor dialog for Tinyfish while its budget stays unconfigured (UI7-07)", async () => {
    const user = userEvent.setup()
    const stub = renderWithManualStub()
    await waitForCard("Tinyfish")
    await openCardAction(user, "Tinyfish", "Set balance")
    const dialog = await screen.findByRole("dialog")
    expect(dialog).toHaveTextContent("Tinyfish")
    expect(dialog).not.toHaveTextContent(/error|failed/i)
    expect(stub.requestsTo("/api/v1/providers/tinyfish/manual-quota").map((request) => request.method)).toContain("GET")
  })

  it("loads an empty manual entry without an error", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {})
    try {
      const stub = renderWithManualStub()
      await waitFor(() => {
        expect(stub.requestsTo("/api/v1/providers/tinyfish/manual-quota")).not.toHaveLength(0)
      })
      await waitForCard("Tinyfish")
      expect(screen.queryByTestId("manual-quota-error")).toBeNull()
      expect(consoleError).not.toHaveBeenCalled()
    } finally {
      consoleError.mockRestore()
    }
  })

  it("accepts Exa balance in USD and stores exact USD allowance and usage", async () => {
    const user = userEvent.setup()
    const stub = renderWithManualStub()
    await waitForCard("Exa")

    await openCardAction(user, "Exa", "Set balance")
    expect(screen.getByLabelText<HTMLInputElement>("Allowance (USD)").value).toBe("")
    expect(screen.getByLabelText<HTMLInputElement>("Balance remaining (USD)").value).toBe("")
    fireEvent.change(screen.getByLabelText("Billing start"), {
      target: { value: "2026-10-01" },
    })
    fireEvent.change(screen.getByLabelText("Billing end"), {
      target: { value: "2026-10-31" },
    })
    fireEvent.change(screen.getByTestId("manual-quota-allowance"), {
      target: { value: "5.00" },
    })
    fireEvent.change(screen.getByTestId("manual-quota-usage"), {
      target: { value: "4.12" },
    })
    await user.click(screen.getByTestId("manual-quota-save"))

    await waitFor(() => {
      expect(stub.requestsTo("/api/v1/providers/exa/manual-quota").map((request) => request.method)).toContain("PUT")
    })
    expect(
      stub.requestsTo("/api/v1/providers/exa/manual-quota").find((request) => request.method === "PUT")?.body,
    ).toEqual({
      billing_start: "2026-10-01",
      billing_end: "2026-10-31",
      allowance: "5.00",
      current_usage: "0.88",
    })
  })

  it("saves a Tinyfish balance as usage in the native payload (UI7-07)", async () => {
    const user = userEvent.setup()
    const stub = renderWithManualStub()
    await waitForCard("Tinyfish")

    await openCardAction(user, "Tinyfish", "Set balance")
    fireEvent.change(screen.getByLabelText("Billing start"), {
      target: { value: "2026-09-01" },
    })
    fireEvent.change(screen.getByLabelText("Billing end"), {
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
      current_usage: "4.12",
    })
  })

  it("locks the sentence-case menu wording and no legacy labels (CARD-3)", async () => {
    const user = userEvent.setup()
    renderWithManualStub()
    await waitForCard("Tinyfish")
    expect(await menuLabels(user, "Tinyfish")).toEqual(["Set balance", "Budget limit", "Balance history"])
    expect(screen.queryByText("Provider Balance")).toBe(null)
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
    expect(screen.queryByRole("button", { name: "Set balance" })).toBe(null)
  })
})

/**
 * Developer role (control read without control edit): the card controls stay
 * visible, but every mutation is rejected with 403. The stub serves reads
 * plus 403 on both PUT paths. Each failed save keeps its alert and its open
 * modal, and nothing persists.
 */
describe("QuotaAnalytics Developer read-only", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("shows Balance and Spend controls but rejects Developer saves with 403 and keeps no data", async () => {
    const stub = installFetchStub((req) => {
      if (req.url === "/api/v1/providers" && req.method === "GET") {
        return ok(allProvidersFixture())
      }
      if (req.url === "/api/v1/routing/config" && req.method === "GET") {
        return ok(routingConfigFixture())
      }
      if (req.url.endsWith("/manual-quota") && req.method === "GET") {
        return ok(null)
      }
      if (req.url.endsWith("/manual-quota") && req.method === "PUT") {
        return err(403, { detail: "insufficient role" })
      }
      if (req.url.includes("/budgets/") && req.method === "PUT") {
        return err(403, { detail: "insufficient role" })
      }
      if (req.url.startsWith("/dashboard")) {
        return ok({
          ...(dashboardFixture({ latest_quota: manualQuotaRows() }) as unknown as Record<
            string,
            unknown
          >),
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
      <FreeSearchProvider
        accountId={DEVELOPER_ACCOUNT_ID}
        canReadControls
        canEditControls={false}
      >
        <QuotaAnalytics />
      </FreeSearchProvider>
    )
    const user = userEvent.setup()

    // Controls stay visible for Developer reads.
    await waitForCard("Tinyfish")
    expect(await menuLabels(user, "Tinyfish")).toEqual(["Set balance", "Budget limit", "Balance history"])

    // Manual save attempt rejects with 403, keeps the alert and the open modal.
    await openCardAction(user, "Tinyfish", "Set balance")
    await screen.findByRole("dialog")
    fireEvent.change(screen.getByLabelText("Billing start"), {
      target: { value: "2026-09-01" },
    })
    fireEvent.change(screen.getByLabelText("Billing end"), {
      target: { value: "2026-09-30" },
    })
    fireEvent.change(screen.getByTestId("manual-quota-allowance"), {
      target: { value: "5.00" },
    })
    fireEvent.change(screen.getByTestId("manual-quota-usage"), {
      target: { value: "0.88" },
    })
    await user.click(screen.getByTestId("manual-quota-save"))
    const manualAlert = await screen.findByTestId("manual-quota-error")
    expect(manualAlert).toHaveTextContent("insufficient role")
    expect(screen.getByRole("dialog")).toBeInTheDocument()
    expect(
      stub.requestsTo("/api/v1/providers/tinyfish/manual-quota").map((request) => request.method)
    ).toContain("PUT")

    // Close the manual modal before the grant attempt.
    await user.click(screen.getByTestId("manual-quota-cancel"))
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull()
    })

    // Grant save attempt rejects with 403, keeps the alert and the open modal.
    await openCardAction(user, "Tinyfish", "Budget limit")
    await screen.findByRole("dialog")
    await user.clear(screen.getByLabelText("Search budget (USD)"))
    await user.type(screen.getByLabelText("Search budget (USD)"), "5")
    await user.click(screen.getByRole("button", { name: "Save budget limit" }))
    const grantAlert = await screen.findByRole("alert")
    expect(grantAlert).toHaveTextContent("insufficient role")
    expect(screen.getByRole("dialog")).toBeInTheDocument()
    expect(
      stub.requestsTo(/\/budgets\//).map((request) => request.method)
    ).toContain("PUT")

    // Nothing persists: no estimate appears and no dashboard refresh follows a rejection.
    expect(screen.queryByTestId("manual-quota-estimate-tinyfish")).toBeNull()
    expect(stub.requestsTo(/\/dashboard/).length).toBe(1)
  })
})
