import React from "react"
import { describe, it, expect, afterEach, vi } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { SearchPlayground } from "./SearchPlayground"
import { installFetchStub, ok, err } from "@/test/fetchMock"
import {
  allProvidersFixture,
  routingConfigFixture,
  dashboardFixture,
  searchResponseFixture,
  fetchResponseFixture,
} from "@/test/backendFixtures"

/**
 * C2-REWORK tab contract (RED): the Search/Fetch view-switcher must be the
 * single canonical Tabs(pill) control (`ui/tabs` pill variant, provider-page
 * pill look, always top-right in the page header: role=tab/aria-selected/
 * tabpanel), and the Depth selector must be the single canonical
 * SegmentedControl (role=group, exclusive aria-pressed). The current
 * Tabs(line) view-switcher fails every pill assertion below; the prior
 * line-tab consensus is VOID.
 *
 * Expected churn note: the switcher stays role=tab — every step below
 * addresses it as role=tab inside a pill tablist on purpose.
 *
 * PG-S5 AMENDMENT (number-of-results): the Depth SegmentedControl is
 * DELETED and replaced by a labeled Results number input (spinbutton
 * "Number of results", type number, min 1, max 100, step 1, default 6).
 * The two Depth-group tests below now assert the spinbutton contract;
 * the aria-pressed test asserts zero pressed toggles remain.
 */
function renderPlayground() {
  installFetchStub((req) => {
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(allProvidersFixture())
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
    if (req.url === "/search" && req.method === "POST") {
      return ok(searchResponseFixture())
    }
    if (req.url === "/fetch" && req.method === "POST") {
      return ok(fetchResponseFixture())
    }
    return err(404, { detail: "unhandled test route" })
  })
  return render(
    <FreeSearchProvider>
      <SearchPlayground />
    </FreeSearchProvider>
  )
}

async function ready() {
  await waitFor(() => {
    expect(
      screen.getByPlaceholderText(/Search across all providers/i)
    ).toBeInTheDocument()
  })
}

describe("C2-REWORK AC-C2R-1/AC-C2R-3: SearchPlayground view-switcher is canonical Tabs(pill)", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("exposes exactly Search + Fetch as role=tab inside a tablist", async () => {
    renderPlayground()
    await ready()

    const tablist = screen.getByRole("tablist")
    expect(tablist).toBeInTheDocument()
    const tabs = within(tablist).getAllByRole("tab")
    expect(tabs.map((t) => t.textContent)).toEqual(["Search", "Fetch"])

    // Exactly one panel is mounted: the selected Search panel, linked both ways.
    const searchTab = screen.getByRole("tab", { name: "Search" })
    const searchControls = searchTab.getAttribute("aria-controls")
    const searchId = searchTab.getAttribute("id")
    expect(searchControls?.trim().length).toBeGreaterThan(0)
    expect(searchId?.trim().length).toBeGreaterThan(0)
    const panels = screen.getAllByRole("tabpanel")
    expect(panels).toHaveLength(1)
    expect(panels[0]).toHaveAttribute("id", searchControls!)
    expect(panels[0]).toHaveAttribute("aria-labelledby", searchId!)
  })

  it("uses the ui/tabs pill variant for the view-switcher", async () => {
    renderPlayground()
    await ready()

    const pillList = document.querySelector(
      '[data-slot="tabs-list"][data-variant="pill"]'
    )
    expect(pillList).not.toBeNull()
    expect(pillList!.contains(screen.getByRole("tab", { name: "Search" }))).toBe(true)
    expect(pillList!.contains(screen.getByRole("tab", { name: "Fetch" }))).toBe(true)
    // The VOID line variant is gone from the playground switcher slot.
    expect(
      document.querySelector('[data-slot="tabs-list"][data-variant="line"]')
    ).toBeNull()
  })

  it("marks Search aria-selected=true and Fetch aria-selected=false initially", async () => {
    renderPlayground()
    await ready()

    expect(screen.getByRole("tab", { name: "Search" })).toHaveAttribute(
      "aria-selected",
      "true"
    )
    expect(screen.getByRole("tab", { name: "Fetch" })).toHaveAttribute(
      "aria-selected",
      "false"
    )

    // Linkage target exists even before the Fetch panel mounts on selection.
    const fetchTab = screen.getByRole("tab", { name: "Fetch" })
    expect(fetchTab.getAttribute("aria-controls")?.trim().length).toBeGreaterThan(0)
    expect(fetchTab.getAttribute("id")?.trim().length).toBeGreaterThan(0)
  })

  it("switching to the Fetch tab swaps the hero input and submit action", async () => {
    const user = userEvent.setup()
    renderPlayground()
    await ready()

    await user.click(screen.getByRole("tab", { name: "Fetch" }))

    expect(screen.getByRole("tab", { name: "Fetch" })).toHaveAttribute(
      "aria-selected",
      "true"
    )
    expect(screen.getByRole("tab", { name: "Search" })).toHaveAttribute(
      "aria-selected",
      "false"
    )
    expect(
      screen.getByPlaceholderText(/Enter a URL to fetch/i)
    ).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "Fetch", exact: true })
    ).toBeInTheDocument()

    // Panel swap: the Fetch panel mounts (linked), the Search panel unmounts.
    const searchControls = screen
      .getByRole("tab", { name: "Search" })
      .getAttribute("aria-controls")
    const fetchTabNow = screen.getByRole("tab", { name: "Fetch" })
    const fetchPanels = screen.getAllByRole("tabpanel")
    expect(fetchPanels).toHaveLength(1)
    expect(fetchPanels[0]).toHaveAttribute(
      "id",
      fetchTabNow.getAttribute("aria-controls")!
    )
    expect(fetchPanels[0]).toHaveAttribute(
      "aria-labelledby",
      fetchTabNow.getAttribute("id")!
    )
    expect(document.getElementById(searchControls!)).toBeNull()

    // Swap back: the Search panel remounts, the Fetch panel unmounts.
    await user.click(screen.getByRole("tab", { name: "Search" }))
    expect(
      screen.getByPlaceholderText(/Search across all providers/i)
    ).toBeInTheDocument()
    const searchPanels = screen.getAllByRole("tabpanel")
    expect(searchPanels).toHaveLength(1)
    expect(searchPanels[0]).toHaveAttribute("id", searchControls!)
    expect(
      document.getElementById(fetchTabNow.getAttribute("aria-controls")!)
    ).toBeNull()
  })

  it("arrow keys move focus between tabs; Enter activates selection", async () => {
    const user = userEvent.setup()
    renderPlayground()
    await ready()

    const searchTab = screen.getByRole("tab", { name: "Search" })
    const fetchTab = screen.getByRole("tab", { name: "Fetch" })
    searchTab.focus()
    expect(searchTab).toHaveFocus()

    // Manual activation (Base UI Tabs default): arrows move focus, not selection.
    await user.keyboard("{ArrowRight}")

    await waitFor(() => {
      expect(fetchTab).toHaveFocus()
    })
    expect(searchTab).toHaveAttribute("aria-selected", "true")
    expect(fetchTab).toHaveAttribute("aria-selected", "false")

    await user.keyboard("{Enter}")

    await waitFor(() => {
      expect(screen.getByRole("tab", { name: "Fetch" })).toHaveAttribute("aria-selected", "true")
    })
    expect(screen.getByRole("tab", { name: "Search" })).toHaveAttribute("aria-selected", "false")
  })
})

describe("C2 PG-S5: Results count replaces the Depth SegmentedControl", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("exposes a labeled Results number input (min1 max100 step1 default 6, no Depth group)", async () => {
    renderPlayground()
    await ready()

    // PG-S5: the Depth group is gone entirely.
    expect(
      screen.queryByRole("group", { name: /search depth/i })
    ).toBeNull()
    expect(
      screen.queryByRole("button", { name: "Fast", exact: true })
    ).toBeNull()
    expect(
      screen.queryByRole("button", { name: "Balanced", exact: true })
    ).toBeNull()
    expect(
      screen.queryByRole("button", { name: "Deep", exact: true })
    ).toBeNull()

    const footer = screen.getByTestId("search-composer-footer")
    const spin = within(footer).getByRole("spinbutton", {
      name: "Number of results",
    }) as HTMLInputElement
    expect(spin.getAttribute("type")).toBe("number")
    expect(spin).toHaveAttribute("min", "1")
    expect(spin).toHaveAttribute("max", "100")
    expect(spin).toHaveAttribute("step", "1")
    expect(spin).toHaveValue(6)
    expect(footer.textContent).toMatch(/Results:/)
  })

  it("editing the count updates the field value (user-typed 25)", async () => {
    const user = userEvent.setup()
    renderPlayground()
    await ready()

    const spin = within(
      screen.getByTestId("search-composer-footer")
    ).getByRole("spinbutton", {
      name: "Number of results",
    }) as HTMLInputElement
    await user.clear(spin)
    await user.type(spin, "25")
    expect(spin).toHaveValue(25)
  })
})

describe("C2 AC-C2-3: no hand-rolled mimics in the playground tab/filter slots", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("has no button named Fetch in initial search mode (Fetch is a tab)", async () => {
    renderPlayground()
    await ready()

    expect(
      screen.queryByRole("button", { name: "Fetch", exact: true })
    ).not.toBeInTheDocument()
    expect(
      screen.getByRole("tab", { name: "Fetch" })
    ).toBeInTheDocument()
  })

  it("no aria-pressed toggles remain in the playground (Depth control deleted by PG-S5)", async () => {
    renderPlayground()
    await ready()

    const toggles = screen
      .getAllByRole("button")
      .filter((b) => b.hasAttribute("aria-pressed"))
    expect(toggles).toHaveLength(0)
  })

  it("no tab carries the filter contract (aria-pressed)", async () => {
    renderPlayground()
    await ready()

    for (const tab of screen.getAllByRole("tab")) {
      expect(tab).not.toHaveAttribute("aria-pressed")
    }
    // Tabs switch panels; the switcher must not double as a pressed toggle.
    expect(screen.getByRole("tab", { name: "Search" })).toHaveAttribute(
      "aria-selected",
      "true"
    )
  })
})
