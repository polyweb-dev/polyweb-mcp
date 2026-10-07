import React from "react"
import { describe, it, expect, afterEach, vi } from "vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
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
 * UI7 manual entry through the shell: action-slot buttons read
 * "Provider Balance", the dialog keeps native-anchor transport, and the
 * card USD path translates balance to usage (see useQuotaForm tests
 * for the 5.00/4.12 to 0.88 contract). Covers UI7-07.
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
    <FreeSearchProvider>
      <QuotaAnalytics />
    </FreeSearchProvider>
  )
  return stub
}

describe("QuotaAnalytics manual billing entry (UI7)", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("offers Provider Balance on Brave always and on unbudgeted Parallel, never on Tavily (UI7-07)", async () => {
    renderWithManualStub()
    await waitFor(() => {
      expect(screen.getByTestId("manual-quota-open-brave")).toBeInTheDocument()
    })
    expect(screen.getByTestId("manual-quota-open-brave")).toHaveTextContent("Provider Balance")
    expect(screen.getByTestId("manual-quota-open-parallel")).toHaveTextContent("Provider Balance")
    expect(screen.queryByTestId("manual-quota-open-tavily")).toBe(null)
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

  it("saves a Brave window through the unchanged native payload (UI7-07)", async () => {
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
      const puts = stub.requestsTo("/api/v1/providers/brave/manual-quota")
      expect(puts.map((request) => request.method)).toContain("PUT")
    })
    const puts = stub.requestsTo("/api/v1/providers/brave/manual-quota")
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
      expect(screen.getByTestId("manual-quota-open-brave")).toBeInTheDocument()
    })
    expect(screen.getByTestId("manual-quota-open-brave")).toHaveTextContent("Provider Balance")
    expect(
      screen.getByRole("button", {
        name: "Provider Balance for Brave Search. Records the balance the vendor dashboard shows, as an estimate.",
      }),
    ).toBeInTheDocument()
    expect(screen.queryByText("Balance entry")).toBe(null)
    expect(screen.queryByText("Manual entry")).toBe(null)
  })

  it("shows no legacy overlay row on the new page (UI7-05)", async () => {
    renderWithManualStub()
    await waitFor(() => {
      expect(screen.getByText("Provider actions")).toBeInTheDocument()
    })
    expect(screen.queryByText("Provider quota view")).toBe(null)
    expect(screen.queryByTestId("manual-quota-estimate-brave")).toBe(null)
  })
})
