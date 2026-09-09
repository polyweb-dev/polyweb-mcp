import React from "react"
import { describe, it, expect, afterEach, vi } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { ActivityStream } from "./ActivityStream"
import { installFetchStub, ok, err } from "@/test/fetchMock"
import {
  allProvidersFixture,
  routingConfigFixture,
  dashboardFixture,
} from "@/test/backendFixtures"

/**
 * C2 tab unification (RED): the operation filter (All / Search / Fetch,
 * currently bespoke boxed pills with no group role at ActivityStream L41-58)
 * must be the single canonical SegmentedControl — role=group with an
 * accessible name and exclusive aria-pressed.
 *
 * Deterministic feed: the default dashboard fixture carries exactly one
 * search event (Tavily) and one fetch event (Brave Search).
 */
function renderActivity() {
  installFetchStub((req) => {
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(allProvidersFixture())
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
    return err(404, { detail: "unhandled test route" })
  })
  return render(
    <FreeSearchProvider>
      <ActivityStream />
    </FreeSearchProvider>
  )
}

async function ready() {
  await waitFor(() => {
    expect(screen.getByText("Tavily", { exact: true })).toBeInTheDocument()
  })
  expect(screen.getByText("Brave Search", { exact: true })).toBeInTheDocument()
}

/** The one canonical filter group, found without pinning the exact label. */
function filterGroup(): HTMLElement {
  const groups = screen.getAllByRole("group")
  const match = groups.find(
    (g) =>
      within(g).queryByRole("button", { name: /^all$/i }) &&
      within(g).queryByRole("button", { name: /^fetch$/i })
  )
  expect(match).toBeDefined()
  return match!
}

describe("C2 AC-C2-2/AC-C2-4: ActivityStream filter is a SegmentedControl", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("exposes All/Search/Fetch in a named group, All pressed", async () => {
    renderActivity()
    await ready()

    const group = filterGroup()
    expect(group).toHaveAccessibleName()
    expect(
      ["all", "search", "fetch"].map(
        (label) =>
          within(group)
            .getByRole("button", { name: new RegExp(`^${label}$`, "i") })
            .getAttribute("aria-pressed")
      )
    ).toEqual(["true", "false", "false"])
  })

  it("filter buttons are not tabs", async () => {
    renderActivity()
    await ready()

    const group = filterGroup()
    expect(within(group).queryByRole("tab")).not.toBeInTheDocument()
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument()
  })

  it("choosing Fetch keeps only the fetch event", async () => {
    const user = userEvent.setup()
    renderActivity()
    await ready()

    await user.click(
      within(filterGroup()).getByRole("button", { name: /^fetch$/i })
    )

    await waitFor(() => {
      expect(screen.queryByText("Tavily", { exact: true })).not.toBeInTheDocument()
    })
    expect(screen.getByText("Brave Search", { exact: true })).toBeInTheDocument()
    expect(
      within(filterGroup())
        .getByRole("button", { name: /^fetch$/i })
        .getAttribute("aria-pressed")
    ).toBe("true")
  })

  it("choosing Search keeps only the search event, All restores both", async () => {
    const user = userEvent.setup()
    renderActivity()
    await ready()

    await user.click(
      within(filterGroup()).getByRole("button", { name: /^search$/i })
    )
    await waitFor(() => {
      expect(
        screen.queryByText("Brave Search", { exact: true })
      ).not.toBeInTheDocument()
    })
    expect(screen.getByText("Tavily", { exact: true })).toBeInTheDocument()

    await user.click(
      within(filterGroup()).getByRole("button", { name: /^all$/i })
    )
    await waitFor(() => {
      expect(screen.getByText("Brave Search", { exact: true })).toBeInTheDocument()
    })
    expect(screen.getByText("Tavily", { exact: true })).toBeInTheDocument()
    expect(
      ["all", "search", "fetch"].map(
        (label) =>
          within(filterGroup())
            .getByRole("button", { name: new RegExp(`^${label}$`, "i") })
            .getAttribute("aria-pressed")
      )
    ).toEqual(["true", "false", "false"])
  })
})

describe("C2 AC-C2-3: no hand-rolled filter mimics in ActivityStream", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("every aria-pressed filter toggle lives inside a role=group", async () => {
    renderActivity()
    await ready()

    const toggles = screen
      .getAllByRole("button", { name: /^(all|search|fetch)$/i })
      .filter((b) => b.hasAttribute("aria-pressed"))
    expect(toggles).toHaveLength(3)
    for (const toggle of toggles) {
      expect(toggle.closest('[role="group"]')).not.toBeNull()
    }
  })
})
