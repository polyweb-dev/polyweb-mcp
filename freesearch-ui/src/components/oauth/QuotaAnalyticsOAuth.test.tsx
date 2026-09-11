import React from "react"
import { describe, it, expect, afterEach, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { QuotaAnalytics } from "../quota/QuotaAnalytics"
import { installFetchStub, ok, err, type FetchStub } from "@/test/fetchMock"
import {
  allProvidersFixture,
  routingConfigFixture,
  dashboardFixture,
  type WireDashboardQuota,
} from "@/test/backendFixtures"

/**
 * Parallel OAuth pairing row flow: Connect appears only for Parallel without
 * a usable estimate, pairing flips the row to an authoritative balance with
 * Disconnect, and revoking restores Connect. The device-code stub polls at a
 * 1s server interval, so ready-path assertions allow several seconds.
 */
const parallelUnseeded: WireDashboardQuota[] = []

const parallelBalance: WireDashboardQuota[] = [
  {
    provider: "parallel",
    source: "authoritative",
    observed_at: "2026-09-06T18:00:00Z",
    remaining: "4.12",
    limit: null,
    reset_at: null,
    unit_kind: "USD",
    display_unit: "USD",
  },
]

const deviceCodeWire = {
  provider: "parallel",
  user_code: "ABCD-1234",
  verification_uri: "https://platform.parallel.ai/activate",
  verification_uri_complete: "https://platform.parallel.ai/activate?code=ABCD-1234",
  expires_in: 300,
  interval: 1,
}

function renderWithOAuthStub(state: { latest: WireDashboardQuota[]; oauth: unknown }): FetchStub {
  const stub = installFetchStub((req) => {
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(allProvidersFixture())
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url.endsWith("/oauth/device-code") && req.method === "POST") {
      return ok(deviceCodeWire)
    }
    if (req.url.endsWith("/oauth/status") && req.method === "GET") {
      if (state.oauth === null) return err(404, { detail: "no OAuth pairing for 'parallel'" })
      return ok(state.oauth)
    }
    if (req.url.endsWith("/oauth") && req.method === "DELETE") {
      return new Response(null, { status: 204 })
    }
    if (req.url.startsWith("/dashboard")) {
      return ok(dashboardFixture({ latest_quota: state.latest }))
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

describe("QuotaAnalytics OAuth pairing", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("offers Connect only on Parallel without a usable estimate", async () => {
    renderWithOAuthStub({ latest: parallelUnseeded, oauth: null })
    await waitFor(() => {
      expect(screen.getByText("Parallel quota", { exact: true })).toBeInTheDocument()
    })
    expect(screen.getByTestId("oauth-device-open-parallel")).toHaveTextContent("Connect")
    expect(screen.queryByTestId("oauth-device-disconnect")).toBeNull()
    expect(screen.queryByTestId("oauth-device-open-exa")).toBeNull()
    expect(screen.queryByTestId("oauth-device-open-brave")).toBeNull()
  })

  it("pairs through the modal, shows the balance with Disconnect, then revokes", async () => {
    const user = userEvent.setup()
    const state: { latest: WireDashboardQuota[]; oauth: unknown } = {
      latest: parallelUnseeded,
      oauth: null,
    }
    const stub = renderWithOAuthStub(state)
    await waitFor(() => {
      expect(screen.getByTestId("oauth-device-open-parallel")).toBeInTheDocument()
    })

    await user.click(screen.getByTestId("oauth-device-open-parallel"))
    expect(await screen.findByTestId("oauth-device-user-code")).toHaveTextContent("ABCD-1234")

    state.oauth = { provider: "parallel", status: "ready", expires_in: null }
    state.latest = parallelBalance
    await waitFor(
      () => {
        expect(screen.queryByTestId("oauth-device-user-code")).toBeNull()
      },
      { timeout: 8000 }
    )
    expect(await screen.findByText("Balance available")).toBeInTheDocument()
    expect(screen.getByText("4.12/— USD")).toBeInTheDocument()
    expect(screen.getByTestId("oauth-device-disconnect")).toBeInTheDocument()
    expect(screen.queryByTestId("oauth-device-open-parallel")).toBeNull()

    await user.click(screen.getByTestId("oauth-device-disconnect"))
    state.latest = parallelUnseeded
    state.oauth = null
    await user.click(screen.getByTestId("oauth-device-confirm-disconnect"))
    await waitFor(() => {
      expect(screen.getByTestId("oauth-device-open-parallel")).toBeInTheDocument()
    })
    const deletes = stub.requestsTo("/api/v1/providers/parallel/oauth")
    expect(deletes.map((request) => request.method)).toContain("DELETE")
  })

  it("hides Connect while a manual estimate already leads the row", async () => {
    installFetchStub((req) => {
      if (req.url === "/api/v1/providers" && req.method === "GET") {
        return ok(allProvidersFixture())
      }
      if (req.url === "/api/v1/routing/config" && req.method === "GET") {
        return ok(routingConfigFixture())
      }
      if (req.url.endsWith("/manual-quota") && req.method === "GET") {
        return ok({
          provider: "parallel",
          billing_start: "2026-09-01",
          billing_end: "2026-09-30",
          allowance: "5.00",
          current_usage: "0.88",
        })
      }
      if (req.url.endsWith("/oauth/status") && req.method === "GET") {
        return err(404, { detail: "no OAuth pairing for 'parallel'" })
      }
      if (req.url.startsWith("/dashboard")) {
        return ok(dashboardFixture({ latest_quota: parallelUnseeded }))
      }
      return err(404, { detail: "unhandled test route" })
    })
    render(
      <FreeSearchProvider>
        <QuotaAnalytics />
      </FreeSearchProvider>
    )
    await waitFor(() => {
      expect(screen.getByTestId("manual-quota-estimate-parallel")).toBeInTheDocument()
    })
    expect(screen.queryByTestId("oauth-device-open-parallel")).toBeNull()
    expect(screen.getByTestId("manual-quota-open-parallel")).toHaveTextContent("Update usage")
  })

  it("keeps the disconnect armed until confirmed or kept", async () => {
    const user = userEvent.setup()
    const state: { latest: WireDashboardQuota[]; oauth: unknown } = {
      latest: parallelBalance,
      oauth: { provider: "parallel", status: "ready", expires_in: null },
    }
    const stub = renderWithOAuthStub(state)
    await waitFor(() => {
      expect(screen.getByTestId("oauth-device-disconnect")).toBeInTheDocument()
    })
    await user.click(screen.getByTestId("oauth-device-disconnect"))
    expect(screen.getByTestId("oauth-device-confirm-disconnect")).toBeInTheDocument()
    await user.click(screen.getByTestId("oauth-device-keep"))
    expect(screen.getByTestId("oauth-device-disconnect")).toBeInTheDocument()
    expect(
      stub.requestsTo("/api/v1/providers/parallel/oauth").filter((r) => r.method === "DELETE")
    ).toHaveLength(0)
  })
})

