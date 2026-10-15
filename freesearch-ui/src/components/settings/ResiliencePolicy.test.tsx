import React from "react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen } from "@testing-library/react"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { ADMIN_ACCOUNT_ID, AGENT_ACCOUNT_ID } from "@/test/authFixtures"
import { ResiliencePolicy } from "./ResiliencePolicy"
import { installFetchStub, ok, err } from "@/test/fetchMock"
import {
  allProvidersFixture,
  routingConfigFixture,
  dashboardFixture,
} from "@/test/backendFixtures"

function renderResilience(canEdit = true) {
  installFetchStub((req) => {
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(allProvidersFixture())
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
    if (req.method === "PUT" && req.url === "/api/v1/routing/config") {
      return ok({ ...routingConfigFixture(), ...((req.body as object) ?? {}) })
    }
    return err(404, { detail: "unhandled test route" })
  })

  return render(
    <FreeSearchProvider
      accountId={canEdit ? ADMIN_ACCOUNT_ID : AGENT_ACCOUNT_ID}
      canReadControls
      canEditControls={canEdit}
    >
      <ResiliencePolicy />
    </FreeSearchProvider>
  )
}

describe("ResiliencePolicy", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("renders resilience depth with NO invented timeout budget", async () => {
    renderResilience()

    expect(await screen.findByText("Cascade depth", { exact: true })).toBeInTheDocument()
    // The honest backend has no per-hop timeout to display: invented copy is gone.
    expect(screen.queryByText("3,000 ms", { exact: true })).not.toBeInTheDocument()
    // The auto-bypass row was deleted: no such claim may render.
    expect(screen.queryByText("Circuit breaker auto-bypass")).toBeNull()
  })

  it("adjusts cascade depth using decrease and increase buttons", async () => {
    renderResilience()

    const decreaseButton = await screen.findByRole("button", { name: "Decrease cascade depth" })
    const increaseButton = screen.getByRole("button", { name: "Increase cascade depth" })

    expect(decreaseButton).toBeInTheDocument()
    expect(increaseButton).toBeInTheDocument()

    fireEvent.click(increaseButton)
    fireEvent.click(decreaseButton)
  })

  it("renders depth value as read-only text when user lacks edit permissions", async () => {
    renderResilience(false)

    expect(await screen.findByText("Cascade depth", { exact: true })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Decrease cascade depth" })).toBeNull()
    expect(screen.queryByRole("button", { name: "Increase cascade depth" })).toBeNull()
  })
})
