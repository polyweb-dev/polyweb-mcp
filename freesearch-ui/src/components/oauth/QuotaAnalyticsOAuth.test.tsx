import React from "react"
import { describe, it, expect, afterEach, vi } from "vitest"
import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { QuotaAnalytics } from "../quota/QuotaAnalytics"
import { installFetchStub, ok, err, type FetchStub } from "@/test/fetchMock"
import { ADMIN_ACCOUNT_ID, DEVELOPER_ACCOUNT_ID } from "@/test/authFixtures"
import {
  allProvidersFixture,
  routingConfigFixture,
  dashboardFixture,
  type WireDashboardQuota,
} from "@/test/backendFixtures"

/**
 * Card-anchored Parallel OAuth pairing (QuotaPage + ProviderLimitsCards).
 *
 * Consolidates QuotaAnalyticsOAuth.test.tsx + parallelOAuthPairing.test.tsx.
 * parallelOAuthPairing.test.tsx is deleted: its Part A headline branches
 * asserted the removed QuotaRow table DOM ("Provider quota view", tbody tr,
 * "Parallel quota", "4.12/— USD", quota-remaining-percent-parallel,
 * manual-quota-estimate-parallel) and its Part B polling/a11y/StrictMode/409
 * state machine duplicates OAuthPairingModal.test.tsx, which covers the modal
 * directly without cards. This file keeps only the live card wiring:
 * Connect iff !hasUsableEstimate && !oauthPaired, Disconnect iff paired,
 * modal open/close, revoke, dev read-only. Parallel never offers Provider
 * Balance: its prepaid USD balance comes from the OAuth Account API
 * (AUTHORITATIVE snapshot), never from a manual seed.
 *
 * Live card anchors: bare "Parallel" heading, oauth-device-open-parallel,
 * oauth-device-disconnect / confirm / keep, credit-info-parallel,
 * limit-history-open-parallel, Refresh Limits. No manual-quota-open-parallel,
 * no tbody, no "{name} quota", no quota-remaining-percent-*, no "4.12/— USD".
 * Connect/Disconnect shares one flex-wrap action row with Refresh Limits,
 * Budget Limit, and History.
 */

const OBSERVED_AT = "2026-09-06T18:00:00Z"

const deviceCodeWire = {
  provider: "parallel",
  user_code: "ABCD-1234",
  verification_uri: "https://platform.parallel.ai/activate",
  verification_uri_complete: "https://platform.parallel.ai/activate?code=ABCD-1234",
  expires_in: 300,
  interval: 60,
}

const pairedBalance: WireDashboardQuota[] = [
  {
    provider: "parallel",
    source: "authoritative",
    observed_at: OBSERVED_AT,
    remaining: "3.75",
    limit: null,
    reset_at: null,
    unit_kind: "USD",
    display_unit: "USD",
  },
]

/** Parallel card with no usable estimate: no pool, no finite views, no percent. */
function parallelNoFundsEntry(): Record<string, unknown> {
  const profile = {
    reference_usd_per_crd: "0.001",
    native_usd_per_unit: "1",
    cost_basis: "priced_native_use",
    price_version: "v2026-09",
    source: "documented",
    estimated: false,
  }
  const record = (operation: string) => ({
    provider: "parallel",
    operation,
    auth_mode: "keyed",
    supported: true,
    transport_available: true,
    rate: null,
    budget: null,
    native_pool_id: null,
    conversion_profile: profile,
    plan_name: "Parallel",
    usage_url: null,
    version: 1,
  })
  const view = (operation: string) => ({
    state: "unavailable",
    operation,
    remaining_crd: null,
    local_remaining_crd: null,
    request_cost_crd: null,
    shared_pool_id: null,
    possible_standard_calls: null,
    price_version: null,
    priced: false,
  })
  return {
    provider: "parallel",
    active_auth_mode: "keyed",
    auths: [
      {
        auth_mode: "keyed",
        transport_available: true,
        search: record("search"),
        fetch: record("fetch"),
        free_tiers: [],
        paid_tiers: [],
        unknown_tiers: [],
        tier_split_known: true,
        aggregate_pool: null,
        crd_views: [view("search"), view("fetch")],
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

interface CardState {
  latest: WireDashboardQuota[]
  oauth: unknown
  manual: unknown | null
  deviceCodeStatus?: number
  deviceCodeDetail?: string
}

function renderOAuthCard(
  state: CardState,
  accountId: string = ADMIN_ACCOUNT_ID,
  canEdit: boolean = true,
): FetchStub {
  let statusCalls = 0
  const stub = installFetchStub((req) => {
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(allProvidersFixture())
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url === "/api/v1/providers/parallel/oauth/device-code" && req.method === "POST") {
      if (state.deviceCodeStatus !== undefined && state.deviceCodeStatus !== 200) {
        return err(state.deviceCodeStatus, { detail: state.deviceCodeDetail ?? "oauth unavailable" })
      }
      return ok(deviceCodeWire)
    }
    if (req.url === "/api/v1/providers/parallel/oauth/status" && req.method === "GET") {
      statusCalls += 1
      if (statusCalls === 1) {
        if (state.oauth === null) return err(404, { detail: "no OAuth pairing for 'parallel'" })
        return ok(state.oauth)
      }
      // Row-mount consumed the first call; modal polls see pending so an
      // open dialog stays pending (interval 60 means it rarely polls here).
      if (state.oauth === null) {
        return ok({ provider: "parallel", status: "pending", expires_in: 299 })
      }
      return ok(state.oauth)
    }
    if (req.url === "/api/v1/providers/parallel/oauth" && req.method === "DELETE") {
      return ok({ provider: "parallel", deleted: true })
    }
    if (req.url.endsWith("/manual-quota") && req.method === "GET") {
      if (state.manual !== null) return ok(state.manual)
      return err(404, { detail: "no manual quota" })
    }
    if (req.url.startsWith("/dashboard")) {
      const base = dashboardFixture({ latest_quota: state.latest }) as unknown as Record<
        string,
        unknown
      >
      return ok({ ...base, provider_limits: [parallelNoFundsEntry()], crd_usage_totals: [] })
    }
    return err(404, { detail: "unhandled test route" })
  })
  render(
    <FreeSearchProvider accountId={accountId} canReadControls canEditControls={canEdit}>
      <QuotaAnalytics />
    </FreeSearchProvider>,
  )
  return stub
}

async function waitForParallelCard(): Promise<HTMLElement> {
  await waitFor(
    () => {
      expect(screen.getByRole("heading", { name: "Parallel" })).toBeInTheDocument()
    },
    { timeout: 8000 },
  )
  return screen.getByRole("heading", { name: "Parallel" }).closest("article") as HTMLElement
}

describe("QuotaAnalyticsOAuth.test.tsx", () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it("offers Connect only on Parallel without a usable estimate", async () => {
    renderOAuthCard({ latest: [], oauth: null, manual: null })
    await waitForParallelCard()
    await waitFor(
      () => {
        expect(screen.getByTestId("oauth-device-open-parallel")).toBeInTheDocument()
      },
      { timeout: 8000 },
    )
    expect(screen.getByTestId("oauth-device-open-parallel")).toHaveTextContent("Connect")
    expect(screen.queryByTestId("oauth-device-disconnect")).toBeNull()
    expect(screen.queryByTestId("oauth-device-open-exa")).toBeNull()
    expect(screen.queryByTestId("oauth-device-open-brave")).toBeNull()
    // Parallel never offers Provider Balance; its balance comes from OAuth.
    expect(screen.queryByTestId("manual-quota-open-parallel")).toBeNull()
    // Connect shares one flex-wrap action row with the card actions.
    const connect = screen.getByTestId("oauth-device-open-parallel")
    const actionRow = connect.closest("div.flex.flex-wrap")
    expect(actionRow?.textContent).toContain("Refresh Limits")
    expect(actionRow?.textContent).toContain("Budget Limit")
    expect(actionRow?.textContent).toContain("History")
    expect(actionRow?.textContent).toContain("Connect")
    // Card anchors present; removed table DOM stays absent.
    expect(screen.getByTestId("limit-history-open-parallel")).toBeInTheDocument()
    expect(screen.queryByTestId("quota-remaining-percent-parallel")).toBeNull()
    expect(screen.queryByTestId("manual-quota-estimate-parallel")).toBeNull()
    expect(screen.queryByText("Parallel quota", { exact: true })).toBeNull()
    expect(screen.queryByText("Provider quota view", { exact: true })).toBeNull()
  })

  it("shows Disconnect when the OAuth status is paired", async () => {
    renderOAuthCard({
      latest: [],
      oauth: { provider: "parallel", status: "ready", expires_in: null },
      manual: null,
    })
    await waitForParallelCard()
    await waitFor(
      () => {
        expect(screen.getByTestId("oauth-device-disconnect")).toBeInTheDocument()
      },
      { timeout: 8000 },
    )
    expect(screen.queryByTestId("oauth-device-open-parallel")).toBeNull()
    // Balance stays hidden after pairing; Disconnect shares the action row.
    expect(screen.queryByTestId("manual-quota-open-parallel")).toBeNull()
    const disconnect = screen.getByTestId("oauth-device-disconnect")
    const actionRow = disconnect.closest("div.flex.flex-wrap")
    expect(actionRow?.textContent).toContain("Disconnect")
    expect(actionRow?.textContent).toContain("History")
  })

  it("shows Disconnect from an authoritative snapshot even when status is unreachable", async () => {
    renderOAuthCard({ latest: pairedBalance, oauth: null, manual: null })
    await waitForParallelCard()
    await waitFor(
      () => {
        expect(screen.getByTestId("oauth-device-disconnect")).toBeInTheDocument()
      },
      { timeout: 8000 },
    )
    expect(screen.queryByTestId("oauth-device-open-parallel")).toBeNull()
    expect(screen.queryByTestId("manual-quota-open-parallel")).toBeNull()
  })

  it("ignores a manual stub for Parallel: no Balance, Connect stays", async () => {
    renderOAuthCard({
      latest: [],
      oauth: null,
      manual: {
        provider: "parallel",
        billing_start: "2026-09-01",
        billing_end: "2026-09-30",
        allowance: "5.00",
        current_usage: "0.88",
      },
    })
    await waitForParallelCard()
    await waitFor(
      () => {
        expect(screen.getByTestId("oauth-device-open-parallel")).toBeInTheDocument()
      },
      { timeout: 8000 },
    )
    // Parallel is never manual-eligible, so the stub seeds no estimate and no
    // Balance control; Connect stays because there is no usable estimate.
    expect(screen.queryByTestId("manual-quota-open-parallel")).toBeNull()
    expect(screen.queryByTestId("manual-quota-estimate-parallel")).toBeNull()
    expect(screen.getByTestId("oauth-device-open-parallel")).toHaveTextContent("Connect")
  })
})

describe("parallelOAuthPairing.test.tsx", () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it("opens the pairing dialog with a code and closes it", async () => {
    const user = userEvent.setup()
    renderOAuthCard({ latest: [], oauth: null, manual: null })
    await waitForParallelCard()
    await waitFor(
      () => {
        expect(screen.getByTestId("oauth-device-open-parallel")).toBeInTheDocument()
      },
      { timeout: 8000 },
    )
    await user.click(screen.getByTestId("oauth-device-open-parallel"))
    expect(await screen.findByTestId("oauth-device-user-code", undefined, { timeout: 8000 }))
      .toHaveTextContent("ABCD-1234")
    expect(screen.getByTestId("oauth-device-dialog")).toBeInTheDocument()
    await user.click(screen.getByTestId("oauth-device-cancel"))
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull()
    })
    expect(screen.getByTestId("oauth-device-open-parallel")).toBeInTheDocument()
  })

  it("revokes through Disconnect confirm and calls DELETE", async () => {
    const user = userEvent.setup()
    const stub = renderOAuthCard({
      latest: pairedBalance,
      oauth: { provider: "parallel", status: "ready", expires_in: null },
      manual: null,
    })
    await waitForParallelCard()
    await waitFor(
      () => {
        expect(screen.getByTestId("oauth-device-disconnect")).toBeInTheDocument()
      },
      { timeout: 8000 },
    )
    await user.click(screen.getByTestId("oauth-device-disconnect"))
    expect(await screen.findByTestId("oauth-device-confirm-disconnect")).toBeInTheDocument()
    await user.click(screen.getByTestId("oauth-device-confirm-disconnect"))
    await waitFor(() => {
      expect(
        stub.requestsTo("/api/v1/providers/parallel/oauth").map((request) => request.method),
      ).toContain("DELETE")
    })
    expect(screen.queryByRole("alert")).toBeNull()
  })
})

describe("QuotaAnalytics OAuth pairing (Developer read-only)", () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it("renders the Parallel card for developers and rejects the pairing POST with 403", async () => {
    const user = userEvent.setup()
    renderOAuthCard(
      {
        latest: [],
        oauth: null,
        manual: null,
        deviceCodeStatus: 403,
        deviceCodeDetail: "insufficient role",
      },
      DEVELOPER_ACCOUNT_ID,
      false,
    )
    const card = await waitForParallelCard()
    expect(card.tagName).toBe("ARTICLE")
    expect(screen.getByTestId("limit-history-open-parallel")).toBeInTheDocument()
    await waitFor(
      () => {
        expect(screen.getByTestId("oauth-device-open-parallel")).toBeInTheDocument()
      },
      { timeout: 8000 },
    )
    await user.click(screen.getByTestId("oauth-device-open-parallel"))
    const alert = await screen.findByRole("alert", undefined, { timeout: 8000 })
    expect(alert.textContent).toContain("insufficient role")
    expect(screen.getByRole("dialog")).toBeInTheDocument()
  })
})
