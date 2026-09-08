import React from "react"
import { describe, it, expect, afterEach, vi } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { ProviderMatrix } from "./ProviderMatrix"
import { installFetchStub, ok, err } from "@/test/fetchMock"
import {
  allProvidersFixture,
  routingConfigFixture,
  dashboardFixture,
} from "@/test/backendFixtures"

/**
 * C2 tab unification (RED): the provider capability filter (All / Search /
 * Fetch / Keyless, currently bespoke boxed pills with no group role at
 * ProviderMatrix L54-72) must be the single canonical SegmentedControl —
 * role=group with an accessible name and exclusive aria-pressed.
 */
function renderMatrix() {
  installFetchStub((req) => {
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(allProvidersFixture())
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
    if (req.method === "POST" && req.url.endsWith("/circuit-breaker/reset")) {
      return ok({ provider: "x", state: "closed", updated_at: "2026-09-06T10:06:00Z" })
    }
    return err(404, { detail: "unhandled test route" })
  })
  return render(
    <FreeSearchProvider>
      <ProviderMatrix />
    </FreeSearchProvider>
  )
}

async function ready() {
  await waitFor(() => {
    expect(screen.getByText("Brave Search", { exact: true })).toBeInTheDocument()
  })
}

/** The one canonical filter group, found without pinning the exact label. */
function filterGroup(): HTMLElement {
  const groups = screen.getAllByRole("group")
  const match = groups.find(
    (g) =>
      within(g).queryByRole("button", { name: /^all$/i }) &&
      within(g).queryByRole("button", { name: /^keyless$/i })
  )
  expect(match).toBeDefined()
  return match!
}

function rowCount(): number {
  return screen.getAllByRole("button", { name: /^(Trip|Reset)$/ }).length
}

describe("C2 AC-C2-2/AC-C2-4: ProviderMatrix filter is a SegmentedControl", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("exposes All/Search/Fetch/Keyless in a named group, All pressed", async () => {
    renderMatrix()
    await ready()

    const group = filterGroup()
    expect(group).toHaveAccessibleName()
    expect(
      ["all", "search", "fetch", "keyless"].map(
        (label) =>
          within(group)
            .getByRole("button", { name: new RegExp(`^${label}$`, "i") })
            .getAttribute("aria-pressed")
      )
    ).toEqual(["true", "false", "false", "false"])
  })

  it("filter buttons are not tabs", async () => {
    renderMatrix()
    await ready()

    const group = filterGroup()
    expect(within(group).queryByRole("tab")).not.toBeInTheDocument()
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument()
  })

  it("choosing Fetch shows the 4 fetch-capable providers only", async () => {
    const user = userEvent.setup()
    renderMatrix()
    await ready()
    expect(rowCount()).toBe(7)

    await user.click(
      within(filterGroup()).getByRole("button", { name: /^fetch$/i })
    )

    await waitFor(() => {
      expect(rowCount()).toBe(4)
    })
    expect(
      within(filterGroup())
        .getByRole("button", { name: /^fetch$/i })
        .getAttribute("aria-pressed")
    ).toBe("true")
    expect(screen.queryByText("Brave Search", { exact: true })).not.toBeInTheDocument()
    expect(screen.queryByText("Exa", { exact: true })).not.toBeInTheDocument()
    expect(screen.getByText("Keenable", { exact: true })).toBeInTheDocument()
    expect(screen.getByText("Tavily", { exact: true })).toBeInTheDocument()
  })

  it("choosing Keyless isolates the single keyless-tier provider", async () => {
    const user = userEvent.setup()
    renderMatrix()
    await ready()

    await user.click(
      within(filterGroup()).getByRole("button", { name: /^keyless$/i })
    )

    await waitFor(() => {
      expect(rowCount()).toBe(1)
    })
    expect(screen.getByText("Keenable", { exact: true })).toBeInTheDocument()
    expect(screen.queryByText("Tavily", { exact: true })).not.toBeInTheDocument()
    expect(screen.queryByText("Brave Search", { exact: true })).not.toBeInTheDocument()
  })

  it("returning to All restores all 7 providers with exclusive pressed state", async () => {
    const user = userEvent.setup()
    renderMatrix()
    await ready()

    await user.click(
      within(filterGroup()).getByRole("button", { name: /^fetch$/i })
    )
    await waitFor(() => {
      expect(rowCount()).toBe(4)
    })
    await user.click(
      within(filterGroup()).getByRole("button", { name: /^all$/i })
    )

    await waitFor(() => {
      expect(rowCount()).toBe(7)
    })
    expect(
      ["all", "search", "fetch", "keyless"].map(
        (label) =>
          within(filterGroup())
            .getByRole("button", { name: new RegExp(`^${label}$`, "i") })
            .getAttribute("aria-pressed")
      )
    ).toEqual(["true", "false", "false", "false"])
  })
})

describe("C2 AC-C2-3: no hand-rolled filter mimics in ProviderMatrix", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("every aria-pressed filter toggle lives inside a role=group", async () => {
    renderMatrix()
    await ready()

    const toggles = screen
      .getAllByRole("button", { name: /^(all|search|fetch|keyless)$/i })
      .filter((b) => b.hasAttribute("aria-pressed"))
    expect(toggles).toHaveLength(4)
    for (const toggle of toggles) {
      expect(toggle.closest('[role="group"]')).not.toBeNull()
    }
  })
})
