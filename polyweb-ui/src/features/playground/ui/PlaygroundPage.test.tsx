import React from "react"
import { describe, it, expect, afterEach, vi } from "vitest"
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react"
import { PlaygroundHarness } from "@/test/renderPlayground"
import { PLAYGROUND_PROJECT_ID, answerProjectProviders as answerProviderView } from "@/test/projectPlayground"
import { installFetchStub, ok, err, deferred } from "@/test/fetchMock"
import type { FetchStub } from "@/test/fetchMock"
import { allProvidersFixture, routingConfigFixture, dashboardFixture, searchResponseFixture, fetchResponseFixture } from "@/test/backendFixtures"
import userEvent from "@testing-library/user-event"
import { readFileSync, existsSync, readdirSync } from "node:fs"
import path from "node:path"
import { PLAYGROUND_PERSIST_VERSION, playgroundPersistKey } from "@/store/playgroundPersistence"
import { ADMIN_ACCOUNT_ID } from "@/test/authFixtures"
import { initialPlaygroundState } from "@/store/playgroundSlice"
import type { SearchResponse } from "@/domains/execution"

function answerProjectProviders(req: Parameters<typeof answerProviderView>[0]): Response | null {
  if (req.method === "GET" && req.url === `/api/v1/projects/${PLAYGROUND_PROJECT_ID}/routing/order`) {
    const provider = (id: string) => ({ provider: id, name: id, call_cost_usd: null, keyless: false })
    const operation = (ids: string[]) => ({
      strategy: "custom", providers: ids.map(provider), has_saved_custom: true, not_allowed: [],
    })
    return ok({
      revision: 1,
      search: operation(["brave", "keenable", "tavily", "exa", "firecrawl", "you", "parallel", "tinyfish"]),
      fetch: operation(["keenable", "tavily", "exa", "firecrawl", "you", "parallel", "tinyfish"]),
    })
  }
  return answerProviderView(req)
}

/**
 * Open the shared provider picker and choose one row by its visible name.
 * Rows carry role option only while the list is open, so the open click
 * must come first. Returns the trigger button for text asserts.
 */
async function pinProvider(testId: string, name: string): Promise<HTMLElement> {
  const trigger = screen.getByTestId(testId)
  fireEvent.click(trigger)
  const row = await screen.findByRole("option", { name })
  fireEvent.click(row)
  return trigger
}

describe("SearchPlayground.test.tsx", () => {

/**
 * RED update: search now flows through the live backend (mocked fetch).
 * Results show real mapped fixture titles with a SINGLE-entry waterfall and
 * no per-attempt trace note; failures show a banner while
 * keeping the last-good results.
 */
function renderWithBackend(
  searchHandler?: (req: { url: string }) => Response,
  fetchHandler?: (req: { url: string }) => Response
) {
  const stub = installFetchStub((req) => {
    const projectView = answerProjectProviders(req)
    if (projectView !== null) return projectView
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(allProvidersFixture())
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
    if (req.url === "/search" && req.method === "POST") {
      return searchHandler ? searchHandler(req) : ok(searchResponseFixture())
    }
    if (req.url === "/fetch" && req.method === "POST") {
      return fetchHandler ? fetchHandler(req) : ok(fetchResponseFixture())
    }
    return err(404, { detail: "unhandled test route" })
  })
  const view = render(
    <PlaygroundHarness />
  )
  return { stub, ...view }
}

async function submitQuery(query: string) {
  const input = screen.getByPlaceholderText(
    /Search the web/i
  ) as HTMLInputElement
  fireEvent.change(input, { target: { value: query } })
  fireEvent.submit(input.closest("form")!)
}

describe("SearchPlayground (live backend)", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("renders mode toggles and search form", async () => {
    renderWithBackend()
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/Search the web/i)).toBeInTheDocument()
    })
    expect(screen.getAllByText("Search").length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText("Fetch")).toBeInTheDocument()
  })

  it("executes search and displays the real mapped results", async () => {
    renderWithBackend()
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/Search the web/i)).toBeInTheDocument()
    })

    await submitQuery("live backend query")

    await waitFor(() => {
      expect(screen.getByText("Live backend result one")).toBeInTheDocument()
    })
    expect(screen.getByText("Live backend result two")).toBeInTheDocument()
    // Mock-template copy must never appear for live results
    expect(document.body.textContent).not.toContain("Comprehensive Architecture")
  })

  it("renders exactly ONE waterfall entry with no trace-unavailable note", async () => {
    renderWithBackend()
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/Search the web/i)).toBeInTheDocument()
    })

    await submitQuery("live backend query")

    await waitFor(() => {
      expect(screen.getByText("Live backend result one")).toBeInTheDocument()
    })
    // Single-entry waterfall: the shared JsonViewer carries exactly one entry
    // once its collapsed nodes are opened (lazy-mount contract).
    const inspectorToggle = screen.getByText(/Inspect raw JSON/i)
    fireEvent.click(inspectorToggle)
    await waitFor(() => {
      expect(screen.getByRole("group", { name: "Raw search response" })).toBeInTheDocument()
    })
    for (let round = 0; round < 6; round += 1) {
      const closed = document.querySelectorAll(
        '[aria-label="Raw search response"] details:not([open]) > summary'
      )
      if (closed.length === 0) break
      closed.forEach((summary) => {
        fireEvent.click(summary)
      })
    }
    await waitFor(() => {
      const occurrences = (document.body.textContent?.match(/resultsCount/g) ?? []).length
      expect(occurrences).toBe(1)
    })
    // No per-attempt trace note exists in the UI: WaterfallPanel renders
    // timings only, so the page must show no unavailable-trace text.
    expect(screen.queryByText(/trace (is )?unavailable|waterfall unavailable/i)).not.toBeInTheDocument()
    // Never fake multi-hop cascade text for a single-attempt response
    expect(document.body.textContent).not.toMatch(/[2-9]\d* hops evaluated/)
  })

  it("shows an error banner on search failure", async () => {
    renderWithBackend(() => err(503, { detail: "no provider is configured" }))
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/Search the web/i)).toBeInTheDocument()
    })

    await submitQuery("live backend query")

    await waitFor(() => {
      expect(screen.getByText(/No provider is set up for this project/)).toBeInTheDocument()
    })
    expect(screen.queryByText("Live backend result one")).not.toBeInTheDocument()
  })

  it("keeps the last-good results visible when a later search fails", async () => {
    let shouldFail = false
    renderWithBackend(() =>
      shouldFail ? err(503, { detail: "backend went away" }) : ok(searchResponseFixture())
    )
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/Search the web/i)).toBeInTheDocument()
    })

    await submitQuery("first query")
    await waitFor(() => {
      expect(screen.getByText("Live backend result one")).toBeInTheDocument()
    })

    shouldFail = true
    await submitQuery("second query")

    await waitFor(() => {
      expect(screen.getByText(/backend went away/i)).toBeInTheDocument()
    })
    expect(screen.getByText("Live backend result one")).toBeInTheDocument()
  })

  it("resets an ineligible search-only provider when switching to Fetch", async () => {
    const { stub } = renderWithBackend()
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/Search the web/i)).toBeInTheDocument()
    })

    // Brave is search-only: pick it in the search provider filter. The
    // catalog arrives asynchronously, so open the picker and wait for its row.
    const searchTrigger = await pinProvider("playground-search-provider", "Brave Search")
    expect(searchTrigger.textContent).toContain("Brave Search")

    // Switching operations must clear the selected-provider state because
    // Brave cannot serve fetches.
    fireEvent.click(screen.getByRole("tab", { name: "Fetch", exact: true }))

    const fetchTrigger = screen.getByTestId("playground-fetch-provider")
    expect(fetchTrigger.textContent).toContain("Auto")

    const urlInput = screen.getByPlaceholderText(
      /URL to fetch/i
    ) as HTMLInputElement
    fireEvent.change(urlInput, { target: { value: "https://example.com/doc" } })
    fireEvent.submit(urlInput.closest("form")!)

    await waitFor(() => {
      expect(stub.requestsTo("/fetch")).toHaveLength(1)
    })
    expect(stub.requestsTo("/fetch")[0].body).toEqual({
      project_id: PLAYGROUND_PROJECT_ID,
      url: "https://example.com/doc",
      max_chars: null,
      routing: { mode: "auto", providers: [], allow_fallback: true },
    })
  })

  it("labels telemetry as cost, not native credits", async () => {
    renderWithBackend()
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/Search the web/i)).toBeInTheDocument()
    })

    await submitQuery("live backend query")

    await waitFor(() => {
      expect(screen.getByText("Live backend result one")).toBeInTheDocument()
    })
    expect(screen.getByText("Cost")).toBeInTheDocument()
    expect(screen.queryByText("Credits")).not.toBeInTheDocument()
    expect(screen.queryByText("Units")).not.toBeInTheDocument()
  })

  it("renders fetch content length as UTF-8 bytes, not JS chars", async () => {
    const content = "héllo 日本語 world"
    const expectedBytes = new TextEncoder().encode(content).length
    // Sanity: the fixture is genuinely multi-byte (bytes > chars).
    expect(expectedBytes).toBeGreaterThan(content.length)

    renderWithBackend(
      undefined,
      () =>
        ok(
          fetchResponseFixture({
            document: {
              url: "https://example.com/doc",
              content,
              title: "Byte doc",
              content_type: "text/markdown",
              fetched_at: "2026-09-06T10:03:00Z",
              metadata: {},
            },
          })
        )
    )
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/Search the web/i)).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole("tab", { name: "Fetch", exact: true }))

    const urlInput = screen.getByPlaceholderText(
      /URL to fetch/i
    ) as HTMLInputElement
    fireEvent.change(urlInput, { target: { value: "https://example.com/doc" } })
    fireEvent.submit(urlInput.closest("form")!)

    await waitFor(() => {
      expect(screen.getByText("Byte doc")).toBeInTheDocument()
    })
    expect(screen.getByText(`${expectedBytes} bytes`)).toBeInTheDocument()
  })

  it("executes fanout search across all providers when All Providers is selected", async () => {
    let capturedBody: unknown = null
    renderWithBackend((req) => {
      capturedBody = (req as unknown as { body: unknown }).body
      return ok({
        query: "fanout test",
        provider: "aggregated",
        total_results: 1,
        results: [
          {
            title: "Fused Multi-Engine Hit",
            url: "https://example.com/consensus",
            snippet: "Verified snippet content",
            score: 0.95,
            source: "exa, brave",
            metadata: {
              sources: ["exa", "brave"],
              source_ranks: { exa: 1, brave: 2 },
              rrf_score: 0.032,
            },
          },
        ],
        participating_providers: ["exa", "brave"],
      })
    })

    await waitFor(() => {
      expect(screen.getByPlaceholderText(/Search the web/i)).toBeInTheDocument()
    })

    const searchTrigger = await pinProvider(
      "playground-search-provider",
      "All providers"
    )
    expect(searchTrigger.textContent).toContain("All providers")

    await submitQuery("fanout test")

    await waitFor(() => {
      expect(screen.getByText("Fused Multi-Engine Hit")).toBeInTheDocument()
    })
    expect(capturedBody).toMatchObject({
      query: "fanout test",
      fanout: true,
      routing: { mode: "fanout" },
    })
    expect(screen.getByText(/2 engines/)).toBeInTheDocument()
    expect(screen.getByText(/All Providers \(2 fused\)/i)).toBeInTheDocument()
  })
})

/**
 * Characterization (PLAN §6.3 item 10): Playground selection, inspector,
 * waterfall note, and raw-JSON behavior must stay unchanged when
 * `SearchResults` adopts the shared `InspectorSplitPane` and
 * `LatencyWaterfall` gains additive selectable rows. These pin the current
 * behavior and SHOULD PASS both before and after that refactor.
 * Ported from `SearchPlayground.test.tsx` (OpenTelemetry branch) into the
 * canonical `PlaygroundPage.test.tsx` consolidation.
 */
describe("SearchPlayground inspector contract (characterization)", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("shows the empty inspector prompt before a result is selected", async () => {
    renderWithBackend()
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/Search the web/i)).toBeInTheDocument()
    })

    await submitQuery("live backend query")

    await waitFor(() => {
      expect(screen.getByText("Live backend result one")).toBeInTheDocument()
    })
    expect(screen.getByText("Returned results (2)")).toBeInTheDocument()
    expect(screen.queryByText("Results 2")).not.toBeInTheDocument()
    // One prompt only: the side inspector asks for a selection, the list does not repeat it.
    expect(screen.queryByText("Select item to inspect")).not.toBeInTheDocument()
    // The side inspector is always present: either the empty prompt or the
    // auto-selected first result, depending on controller defaults.
    expect(screen.getByText(/Result details|Select a result to see its details/)).toBeInTheDocument()
  })

  it("selects a result into the side inspector on click", async () => {
    renderWithBackend()
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/Search the web/i)).toBeInTheDocument()
    })

    await submitQuery("live backend query")

    await waitFor(() => {
      expect(screen.getByText("Live backend result one")).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText("Live backend result one"))

    await waitFor(() => {
      expect(screen.getByText("Result details")).toBeInTheDocument()
    })
    expect(screen.getByText("Target URL")).toBeInTheDocument()
    expect(screen.getAllByText("https://example.com/one").length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText("First live snippet.").length).toBeGreaterThanOrEqual(1)
  })

  it("toggles the raw JSON inspector without losing results", async () => {
    renderWithBackend()
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/Search the web/i)).toBeInTheDocument()
    })

    await submitQuery("live backend query")

    await waitFor(() => {
      expect(screen.getByText("Live backend result one")).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText(/Inspect raw JSON/i))
    await waitFor(() => {
      expect(screen.getByRole("group", { name: "Raw search response" })).toBeInTheDocument()
    })
    expect(screen.getByText("Live backend result one")).toBeInTheDocument()

    fireEvent.click(screen.getByText(/Hide raw JSON/i))
    await waitFor(() => {
      expect(screen.queryByRole("group", { name: "Raw search response" })).not.toBeInTheDocument()
    })
    expect(screen.getByText("Live backend result two")).toBeInTheDocument()
  })
})
})

describe("SearchPlayground.c2.test.tsx", () => {

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
    const projectView = answerProjectProviders(req)
    if (projectView !== null) return projectView
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
    <PlaygroundHarness />
  )
}

async function ready() {
  await waitFor(() => {
    expect(
      screen.getByPlaceholderText(/Search the web/i)
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
      screen.getByPlaceholderText(/URL to fetch/i)
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
      screen.getByPlaceholderText(/Search the web/i)
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
    fireEvent.change(spin, { target: { value: "101" } })
    expect(spin).toHaveValue(100)
    fireEvent.change(spin, { target: { value: "6" } })
    expect(spin).toHaveAttribute("step", "1")
    expect(spin).toHaveValue(6)
    expect(footer.textContent).toMatch(/Results/)
  })

  it("editing the count updates the field value (user-typed 25)", async () => {
    renderPlayground()
    await ready()

    const spin = within(
      screen.getByTestId("search-composer-footer")
    ).getByRole("spinbutton", {
      name: "Number of results",
    }) as HTMLInputElement
    // PLAN §3.2 clamps through the shared 1..100 contract: clearing fires
    // onChange("") -> Number("") = 0 -> clamp 1, so clear+append would append
    // onto the clamped "1". Exercise a valid replacement the clamp preserves.
    fireEvent.change(spin, { target: { value: "25" } })
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
})

describe("SearchPlayground.pg-f1.test.tsx", () => {

/**
 * PG-F1 Fetch empty state (BDD Acceptance, RED phase).
 *
 * User bullet (feedback.md L47 intent): Fetch analogue of PG-S1 — centered
 * hero when idle, docked-top on use, smooth transition — PLUS ComposerShell
 * extraction (Fetch ONLY via shared shell; Search stays reference shape, no
 * migration).
 * SEE image yourself: .agents/FEEDBACK/UI/image-12.png (Fetch empty
 * top-anchored void).
 *
 * Plan CONFIRMED under test (polyweb-ui/ ONLY):
 *   - NEW common/ComposerShell.tsx (testIdPrefix slots: box + conditional
 *     divider/footer, exact Search token strings);
 *   - SearchPlayground hasFetchContent (activeFetch||isFetching||fetchError);
 *   - Fetch branch -> ComposerShell testIdPrefix=fetch (inputRow
 *     FileText/url-input/Fetch-button text-only, footer Provider row);
 *   - fetch-layout hero/docked wrapper (same tokens as search-layout);
 *   - Search branch ZERO diff; fetching logic untouched.
 *
 * AC mapping:
 *   AC-PG-F1-1  Idle Fetch hero: Fetch tab shows fetch-layout data-state=hero
 *               with the SAME hero/transition tokens as search-layout
 *               (transition-all duration-300 ease-out
 *               motion-reduce:transition-none + min-h-[55|60vh] max-w-3xl
 *               centered column), composer inside, no doc/error. Top-anchored
 *               void is gone.
 *   AC-PG-F1-2  Dock on submit/loading/success: submit docks the Fetch form
 *               (hasFetchContent), stays docked while isFetching is pending
 *               (Executing... disabled, value retained), results render BELOW
 *               the form in document order. Source owns hasFetchContent as
 *               activeFetch||isFetching||fetchError gating fetch-layout.
 *   AC-PG-F1-3  Errors pin docked + start-clear: first-fetch-failure docks
 *               with the error banner (no doc, URL retained, form survives);
 *               success-then-failure clears via the untouched start-clear
 *               (pending B wipes doc A, terminal failure keeps it wiped with
 *               the B banner + B URL, no stale doc).
 *   AC-PG-F1-4  Same-element transition: hero->docked keeps the SAME form
 *               node, value, and focus (no remount).
 *   AC-PG-F1-5  Composer-via-shell: Fetch inputRow via ComposerShell
 *               testIdPrefix=fetch (fetch-composer box with the EXACT Search
 *               token strings, borderless url-input, text-only Fetch button
 *               with FileText prefix outside the button), conditional
 *               fetch-composer-divider (hr/border-t) + fetch-composer-footer
 *               (muted 13px, Provider row inside, no Results/Depth), source
 *               imports ComposerShell with prefix fetch and zero
 *               search-disturbance (no prefix search, inline search-composer
 *               + search-layout intact).
 *   AC-PG-F1-6  Regressions GREEN before/after: PG-S1 hero/docked+same-form,
 *               PG-S2 icon-button lock, PG-S3 composer gating, PG-S4 per-card
 *               fetch, PG-S5 number contract, header copy, Simulator untouched,
 *               fetching logic untouched (context start-clear/trim/markdown
 *               contract + playground markdown/4000 + Search-only diff).
 *
 * RED expectation: AC-PG-F1-1..F1-5 FAIL cleanly against the current
 * codebase (zero fetch-layout/fetch-composer/divider/footer testids, zero
 * common/ComposerShell.tsx, zero hasFetchContent/fetch-layout seams, bare
 * Fetch input with borderBottom style). AC-PG-F1-6 stays GREEN throughout.
 */

const testDir = import.meta.dirname
// Read the joined playground owner sources and the shell for compatibility assertions.
const playgroundOwnerFiles = [
  "../model/usePlaygroundController.ts",
  "../model/playgroundFetchAction.ts",
  "../model/playgroundExecuteAction.ts",
  "../model/useResultPreview.ts",
  "../ui/PlaygroundPage.tsx",
  "../ui/SearchSection.tsx",
  "../ui/FetchSection.tsx",
  "../ui/SearchComposer.tsx",
  "../ui/SearchOptions.tsx",
  "../ui/FetchComposer.tsx",
  "../ui/SearchResults.tsx",
  "../ui/ResultCard.tsx",
  "../ui/ResultInspector.tsx",
  "../ui/WaterfallPanel.tsx",
  "../ui/FetchResult.tsx",
]
const playgroundSource = playgroundOwnerFiles
  .map((file) => readFileSync(path.resolve(testDir, file), "utf8"))
  .join("\n")
const dashboardShellSource = readFileSync(
  path.resolve(testDir, "../../../app/ProjectWorkspace.tsx"),
  "utf8"
)
const contextSource = readFileSync(
  path.resolve(testDir, "../../../context/PolywebContext.tsx"),
  "utf8"
)
const executionRunnerFiles = [
  "../../../domains/execution/state/useSearchRunner.ts",
  "../../../domains/execution/state/useFetchRunner.ts",
]
const executionSource = executionRunnerFiles
  .map((file) => readFileSync(path.resolve(testDir, file), "utf8"))
  .join("\n")
// PLAN FR-1: content derivation lives in the persisted slice as selectors,
// never as stored fields or inline controller expressions.
const sliceSource = readFileSync(
  path.resolve(testDir, "../../../store/playgroundSlice.ts"),
  "utf8"
)
const commonDir = path.resolve(testDir, "../../../components/common")
const searchDir = path.resolve(testDir, "../../../components/search")
// Slice 4 ownership: the canonical shell lives in shared/ui; common/
// keeps a compatibility shell. Read the owner (same strength) plus the
// shell for the shim-compat assert in the source test below.
const composerShellPath = path.resolve(testDir, "../../../shared/ui/ComposerShell.tsx")
const composerShimPath = path.resolve(testDir, "../../../components/common/ComposerShell.tsx")

function renderWithBackend(
  searchHandler?: (req: { url: string }) => Response | Promise<Response>,
  fetchHandler?: (req: { url: string }) => Response | Promise<Response>
) {
  const stub = installFetchStub((req) => {
    const projectView = answerProjectProviders(req)
    if (projectView !== null) return projectView
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(allProvidersFixture())
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
    if (req.url === "/search" && req.method === "POST") {
      return searchHandler ? searchHandler(req) : ok(searchResponseFixture())
    }
    if (req.url === "/fetch" && req.method === "POST") {
      return fetchHandler ? fetchHandler(req) : ok(fetchResponseFixture())
    }
    return err(404, { detail: "unhandled test route" })
  })
  const view = render(
    <PlaygroundHarness />
  )
  return { stub, ...view }
}

async function readyForSearch() {
  await waitFor(() => {
    expect(
      screen.getByPlaceholderText(/Search the web/i)
    ).toBeInTheDocument()
  })
}

async function gotoFetch() {
  fireEvent.click(screen.getByRole("tab", { name: "Fetch", exact: true }))
  await waitFor(() => {
    expect(
      screen.getByPlaceholderText(/URL to fetch/i)
    ).toBeInTheDocument()
  })
}

async function readyForFetch() {
  await readyForSearch()
  await gotoFetch()
}

function submitFetchUrl(url: string) {
  const input = screen.getByPlaceholderText(
    /URL to fetch/i
  ) as HTMLInputElement
  fireEvent.change(input, { target: { value: url } })
  fireEvent.submit(input.closest("form")!)
  return input
}

const tokens = (className: string): string[] =>
  className.split(/\s+/).filter(Boolean)

function expectTransitionClasses(wrapper: HTMLElement) {
  expect(wrapper).toHaveClass("top-docked", "w-full")
  expect(wrapper.className).not.toMatch(/min-h|max-w|justify-center|transition-all/)
}

function expectHeroGeometry(wrapper: HTMLElement) {
  expect(wrapper.className).not.toMatch(/min-h-\[(55|60)vh\]/)
  expect(wrapper.className).toContain("w-full")
  expect(wrapper.className).toContain("top-docked")
}

function expectComposerBoxClasses(composer: HTMLElement) {
  const cls = composer.className
  const names = tokens(cls)
  expect(cls).toContain("bg-[var(--elevated)]")
  expect(names).toContain("border")
  expect(cls).toContain("border-[var(--border-subtle)]")
  expect(names).toContain("rounded-xl")
  expect(names.some((t) => /^p-\d+$/.test(t))).toBe(true)
  expect(cls).toContain("shadow")
  expect(within(composer).getByRole("textbox").className).toContain("focus-visible:ring-2")
}

describe("PG-F1 AC-PG-F1-1: idle Fetch is a centered hero (Fetch analogue of PG-S1)", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("shows the Fetch form with no doc/error in a centered hero fetch-layout", async () => {
    renderWithBackend()
    await readyForFetch()

    expect(
      screen.getByPlaceholderText(/URL to fetch/i)
    ).toBeInTheDocument()
    expect(screen.queryByText("Live document title")).not.toBeInTheDocument()
    expect(screen.queryByText(/Fetched markdown body/i)).not.toBeInTheDocument()

    const wrapper = screen.getByTestId("fetch-layout")
    expect(wrapper).toHaveAttribute("data-state", "docked")
    expectHeroGeometry(wrapper)
    expectTransitionClasses(wrapper)
    expect(
      wrapper.querySelector('input[placeholder*="URL to fetch"]')
    ).not.toBeNull()
    expect(wrapper.className).toContain("top-docked")
  })

  it("uses the SAME hero/transition tokens as search-layout", async () => {
    renderWithBackend()
    await readyForSearch()

    const searchHero = screen.getByTestId("search-layout")
    expect(searchHero).toHaveAttribute("data-state", "docked")
    const searchClasses = new Set(tokens(searchHero.className))

    await gotoFetch()

    const fetchHero = screen.getByTestId("fetch-layout")
    expect(fetchHero).toHaveAttribute("data-state", "docked")
    // Shared contract: identical transition + hero-geometry tokens.
    for (const token of [
      "top-docked",
      "w-full",
    ]) {
      expect(tokens(fetchHero.className)).toContain(token)
      expect(searchClasses.has(token)).toBe(true)
    }
    expect(fetchHero.className).not.toMatch(/min-h-\[(55|60)vh\]/)
    expect(searchHero.className).not.toMatch(/min-h-\[(55|60)vh\]/)
  })
})

describe("PG-F1 AC-PG-F1-2: submit docks Fetch and keeps it docked while loading", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("docks on submit, stays docked while loading, doc renders below the form", async () => {
    const gate = deferred<Response>()
    renderWithBackend(undefined, () => gate.promise)
    await readyForFetch()

    expect(screen.getByTestId("fetch-layout")).toHaveAttribute(
      "data-state",
      "docked"
    )

    submitFetchUrl("https://example.com/doc")

    await waitFor(() => {
      expect(screen.getByTestId("fetch-layout")).toHaveAttribute(
        "data-state",
        "docked"
      )
    })
    const loadingWrapper = screen.getByTestId("fetch-layout")
    expect(loadingWrapper.className).toContain("top-docked")
    expect(loadingWrapper.className).not.toMatch(/min-h-\[(55|60)vh\]/)
    expectTransitionClasses(loadingWrapper)
    expect(
      screen.getByRole("button", { name: /Executing/i })
    ).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/URL to fetch/i)).toHaveValue(
      "https://example.com/doc"
    )

    gate.resolve(ok(fetchResponseFixture()))

    await waitFor(() => {
      expect(screen.getByText("Live document title")).toBeInTheDocument()
    })
    expect(screen.getByText(/Fetched markdown body/i)).toBeInTheDocument()
    const dockedWrapper = screen.getByTestId("fetch-layout")
    expect(dockedWrapper).toHaveAttribute("data-state", "docked")
    expect(dockedWrapper.className).toContain("top-docked")
    expectTransitionClasses(dockedWrapper)

    const form = screen
      .getByPlaceholderText(/URL to fetch/i)
      .closest("form")!
    const docTitle = screen.getByText("Live document title")
     
    expect(form.compareDocumentPosition(docTitle) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it("owns hasFetchContent as activeFetch||isFetching||fetchError gating fetch-layout", () => {
    // Slice-owned derivation (PLAN §3.2): results, a pending run, or an error
    // count as content; the booleans are selected, never stored.
    expect(sliceSource).toContain("selectHasFetchContent")
    expect(sliceSource).toContain("selectActiveFetch(state) !== null")
    expect(sliceSource).toContain("selectIsFetching(state)")
    expect(sliceSource).toContain("selectFetchError(state) !== null")
    expect(sliceSource).not.toMatch(/hasFetchContent[?]?:\s*boolean/)
    expect(playgroundSource).toContain("hasFetchContent")
    expect(playgroundSource).toMatch(
      /data-state="docked"/
    )
  })
})

describe("PG-F1 AC-PG-F1-3: Fetch errors pin docked-top; start-clear wipes stale docs", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("first-fetch-failure docks the layout with the error and no doc", async () => {
    const { stub } = renderWithBackend(
      undefined,
      () => err(500, { detail: "fetch exploded" })
    )
    await readyForFetch()

    submitFetchUrl("https://example.com/doc")

    await waitFor(() => {
      expect(stub.requestsTo("/fetch")).toHaveLength(1)
    })
    expect(stub.requestsTo("/fetch")[0].body).toEqual({
      project_id: PLAYGROUND_PROJECT_ID,
      url: "https://example.com/doc",
      max_chars: null,
      routing: { mode: "auto", providers: [], allow_fallback: true },
    })

    await waitFor(() => {
      expect(screen.getByText(/fetch exploded/i)).toBeInTheDocument()
    })
    const wrapper = screen.getByTestId("fetch-layout")
    expect(wrapper).toHaveAttribute("data-state", "docked")
    expect(wrapper.className).toContain("top-docked")
    expectTransitionClasses(wrapper)
    expect(
      screen.getByPlaceholderText(/URL to fetch/i)
    ).toBeInTheDocument()
    expect(
      screen.getByPlaceholderText(/URL to fetch/i) as HTMLInputElement
    ).toHaveValue("https://example.com/doc")
    expect(screen.queryByText("Live document title")).not.toBeInTheDocument()
    expect(
      screen.queryByText(/Fetched markdown body/i)
    ).not.toBeInTheDocument()
  })

  it("success-then-failure clears via start-clear (pending wipes doc A, failure keeps it wiped)", async () => {
    const gate = deferred<Response>()
    let fetchCalls = 0
    const { stub } = renderWithBackend(undefined, () => {
      fetchCalls += 1
      if (fetchCalls === 1) return ok(fetchResponseFixture())
      return gate.promise
    })
    await readyForFetch()

    submitFetchUrl("https://example.com/doc")
    await waitFor(() => {
      expect(screen.getByText("Live document title")).toBeInTheDocument()
    })
    expect(screen.getByTestId("fetch-layout")).toHaveAttribute(
      "data-state",
      "docked"
    )

    submitFetchUrl("https://example.com/other")

    await waitFor(() => {
      expect(stub.requestsTo("/fetch")).toHaveLength(2)
    })
    expect(stub.requestsTo("/fetch")[1].body).toMatchObject({
      url: "https://example.com/other",
    })
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Executing...", exact: true })
      ).toBeInTheDocument()
    })
    // Start-clear: prior doc A is GONE while B pends (production clears
    // activeFetch at runFetch START — covers pending + terminal).
    expect(
      screen.getByPlaceholderText(/URL to fetch/i) as HTMLInputElement
    ).toHaveValue("https://example.com/other")
    expect(screen.queryByText("Live document title")).not.toBeInTheDocument()
    expect(
      screen.queryByText(/Fetched markdown body/i)
    ).not.toBeInTheDocument()
    expect(screen.getByTestId("fetch-layout")).toHaveAttribute(
      "data-state",
      "docked"
    )

    gate.resolve(err(500, { detail: "second fetch exploded" }))
    await waitFor(() => {
      expect(screen.getByText(/second fetch exploded/i)).toBeInTheDocument()
    })
    expect(screen.getByRole("tab", { name: "Fetch" })).toHaveAttribute(
      "aria-selected",
      "true"
    )
    expect(
      screen.getByPlaceholderText(/URL to fetch/i) as HTMLInputElement
    ).toHaveValue("https://example.com/other")
    expect(screen.queryByText("Live document title")).not.toBeInTheDocument()
    expect(
      screen.queryByText(/Fetched markdown body/i)
    ).not.toBeInTheDocument()
    expect(screen.getByTestId("fetch-layout")).toHaveAttribute(
      "data-state",
      "docked"
    )
  })
})

describe("PG-F1 AC-PG-F1-4: smooth same-element Fetch transition retains focus and value", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("keeps the SAME Fetch form element, value, and focus across hero->docked", async () => {
    renderWithBackend()
    await readyForFetch()

    const inputBefore = screen.getByPlaceholderText(
      /URL to fetch/i
    ) as HTMLInputElement
    const formBefore = inputBefore.closest("form")!
    const wrapperBefore = screen.getByTestId("fetch-layout")
    expectTransitionClasses(wrapperBefore)

    fireEvent.change(inputBefore, {
      target: { value: "https://example.com/keep" },
    })
    inputBefore.focus()
    expect(inputBefore).toHaveFocus()
    fireEvent.submit(formBefore)

    await waitFor(() => {
      expect(screen.getByText("Live document title")).toBeInTheDocument()
    })

    const inputAfter = screen.getByPlaceholderText(
      /URL to fetch/i
    ) as HTMLInputElement
    const formAfter = inputAfter.closest("form")!
    expect(formAfter).toBe(formBefore)
    expect(inputAfter).toBe(inputBefore)
    expect(inputAfter).toHaveValue("https://example.com/keep")
    expect(inputAfter).toHaveFocus()

    const wrapperAfter = screen.getByTestId("fetch-layout")
    expect(wrapperAfter).toHaveAttribute("data-state", "docked")
    expectTransitionClasses(wrapperAfter)
  })
})

describe("PG-F1 AC-PG-F1-5: Fetch composer via shared ComposerShell (Fetch ONLY)", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("renders the Fetch inputRow inside fetch-composer box with exact Search tokens and borderless input", async () => {
    renderWithBackend()
    await readyForFetch()

    const composer = screen.getByTestId("fetch-composer")
    expectComposerBoxClasses(composer)
    // Exact Search box token strings (shared shell mirrors the reference).
    expect(composer.className).toContain("rounded-xl")
    expect(composer.className).toContain("bg-[var(--elevated)]")
    expect(composer.className).toContain("border-[var(--border-subtle)]")
    expect(composer.className).toContain("shadow-lg")
    // The card border stays neutral; only the focused control shows a ring.
    expect(composer.className).not.toContain("focus-within:")

    const input = screen.getByPlaceholderText(/URL to fetch/i)
    expect(composer.contains(input)).toBe(true)
    const inputEl = input as HTMLInputElement
    expect(inputEl.getAttribute("type")).toBe("url")
    // Box owns the border: the input itself is borderless (no bare underline).
    expect(inputEl.style.borderBottom).toBe("")
    expect((inputEl.getAttribute("style") ?? "").toLowerCase()).not.toContain(
      "border-bottom"
    )
    // FileText prefix lives in the input row inside the box.
    const prefixSvg = composer.querySelector("svg")
    expect(prefixSvg).not.toBeNull()
  })

  it("places conditional divider + footer inside the Fetch box with the Provider row (muted 13px, no Results/Depth)", async () => {
    renderWithBackend()
    await readyForFetch()

    const composer = screen.getByTestId("fetch-composer")
    const divider = screen.getByTestId("fetch-composer-divider")
    expect(composer.contains(divider)).toBe(true)
    expect(divider.tagName.toLowerCase()).toBe("hr")
    expect(divider.className).toContain("border-t")
    expect(divider.className).toContain("border-[var(--border-subtle)]")

    const footer = screen.getByTestId("fetch-composer-footer")
    expect(composer.contains(footer)).toBe(true)
    expect(footer.className).toContain("text-[13px]")
    expect(footer.className).toContain("text-[var(--muted)]")
    // Footer owns the Provider row (exact Search footer token strings).
    expect(footer.textContent).toMatch(/Provider/)
    const trigger = within(footer).getByTestId("playground-fetch-provider")
    expect(trigger).toHaveAccessibleName("Provider")
    expect(trigger.textContent).toContain("Auto")
    fireEvent.click(trigger)
    expect(
      await within(footer).findByRole("option", { name: "Auto" })
    ).toBeInTheDocument()
    // Fetch footer carries no Search-only controls.
    expect(
      within(footer).queryByRole("spinbutton", { name: "Number of results" })
    ).toBeNull()
    expect(
      within(footer).queryByRole("group", { name: /search depth/i })
    ).toBeNull()
    expect(footer.textContent).not.toMatch(/Suggestions/)
    expect(footer.textContent).not.toMatch(/Results/)
  })

  it("keeps the Fetch submit button text-only inside the composer (FileText never inside the button)", async () => {
    renderWithBackend()
    await readyForFetch()

    const composer = screen.getByTestId("fetch-composer")
    const button = screen.getByRole("button", { name: "Fetch", exact: true })
    expect(composer.contains(button)).toBe(true)
    expect(button.textContent?.trim()).toBe("Fetch")
    expect(button.querySelector("svg")).not.toBeNull()
    // Spacing/input-floor contract matches the Search reference.
    expect(tokens(button.className)).toContain("px-5")
    expect(tokens(button.className)).toContain("py-2")
    expect(tokens(button.className)).toContain("inline-flex")
    const input = screen.getByPlaceholderText(
      /URL to fetch/i
    ) as HTMLInputElement
    expect(tokens(input.className).some((t) => t === "pr-32" || t === "pr-36")).toBe(
      true
    )
  })

  it("wires Fetch via ComposerShell testIdPrefix=fetch with zero Search disturbance (source)", () => {
    // Shared shell exists with testIdPrefix slots.
    expect(existsSync(composerShellPath)).toBe(true)
    const shellSource = readFileSync(composerShellPath, "utf8")
    expect(shellSource).toContain("testIdPrefix")
    expect(shellSource).toContain("ComposerShell")
    expect(shellSource).toContain("-composer")
    expect(shellSource).toContain("-composer-divider")
    expect(shellSource).toContain("-composer-footer")
    // Slot contract: input row + conditional divider/footer.
    expect(shellSource).toMatch(/inputRow|children/)
    expect(shellSource).toMatch(/footer/)
    expect(shellSource).toMatch(/&&|\?/)
    // Exact Search token strings live in the shared shell.
    expect(shellSource).toContain("bg-[var(--elevated)]")
    expect(shellSource).toContain("rounded-xl")
    expect(shellSource).not.toContain("focus-within:")
    expect(shellSource).toContain("text-[13px]")
    expect(shellSource).toContain("text-[var(--muted)]")
    // Compat shell removed (CLEANUP 1.1): features import the shared owner directly.
    expect(existsSync(composerShimPath)).toBe(false)

    // Playground imports the shared shell for Fetch ONLY.
    expect(playgroundSource).toMatch(
      /from\s+["']@\/shared\/ui\/ComposerShell["']/
    )
    expect(playgroundSource).toContain("ComposerShell")
    expect(playgroundSource).toMatch(/testIdPrefix\s*=\s*["']fetch["']/)
    // Search is NOT migrated: no search prefix, inline seams intact.
    expect(playgroundSource).not.toMatch(/testIdPrefix\s*=\s*["']search["']/)
    expect(playgroundSource).toContain('data-testid="search-composer"')
    expect(playgroundSource).toContain('data-testid="fetch-layout"')
    expect(playgroundSource).toContain("hasFetchContent")
    // No stray composer files: only the shared shell (compat shell removed).
    const commonFiles: string[] = existsSync(commonDir)
      ? readdirSync(commonDir)
      : []
    expect(commonFiles.filter((f) => /composer/i.test(f))).toEqual([])
    const searchFiles: string[] = existsSync(searchDir)
      ? readdirSync(searchDir)
      : []
    expect(
      searchFiles.filter((f) => /composer/i.test(f) && !/\.test\./.test(f))
    ).toEqual([])
  })
})

describe("PG-F1 AC-PG-F1-6 regressions: PG-S1..S5 + header + Simulator + logic untouched", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("PG-S1 hero->docked + same-form Search contract intact", async () => {
    renderWithBackend()
    await readyForSearch()

    const hero = screen.getByTestId("search-layout")
    expect(hero).toHaveAttribute("data-state", "docked")
    expect(hero.className).not.toMatch(/min-h-\[(55|60)vh\]/)
    expect(hero.className).toContain("w-full")
    expect(hero.className).toContain("top-docked")
    for (const token of [
      "top-docked",
      "w-full",
    ]) {
      expect(hero.className).toContain(token)
    }

    const inputBefore = screen.getByPlaceholderText(
      /Search the web/i
    ) as HTMLInputElement
    const formBefore = inputBefore.closest("form")!
    fireEvent.change(inputBefore, { target: { value: "s1 lock query" } })
    fireEvent.submit(formBefore)

    await waitFor(() => {
      expect(screen.getByText("Live backend result one")).toBeInTheDocument()
    })
    expect(screen.getByTestId("search-layout")).toHaveAttribute(
      "data-state",
      "docked"
    )
    expect(screen.getByTestId("search-layout").className).toContain(
      "top-docked"
    )
    const inputAfter = screen.getByPlaceholderText(
      /Search the web/i
    ) as HTMLInputElement
    expect(inputAfter.closest("form")).toBe(formBefore)
    expect(inputAfter).toHaveValue("s1 lock query")
    expect(
      screen.getByRole("heading", { name: "Playground" })
    ).toBeInTheDocument()
  })

  it("PG-S2 Search icon-button lock intact; Fetch stays text-only", async () => {
    renderWithBackend()
    await readyForSearch()

    const button = screen.getByRole("button", { name: "Search", exact: true })
    expect(button.textContent?.trim()).toBe("Search")
    const svg = button.querySelector("svg")
    expect(svg).not.toBeNull()
    expect(tokens(svg!.getAttribute("class") ?? "")).toContain("size-3.5")
    const hidden =
      svg!.getAttribute("aria-hidden") === "true" ||
      svg!.closest('[aria-hidden="true"]') !== null
    expect(hidden).toBe(true)
    const names = tokens(button.className)
    expect(names).toContain("h-8")
    expect(names).toContain("px-4")
    expect(names).toContain("gap-2")
    expect(names).not.toContain("px-5")
    expect(names).not.toContain("py-2")

    const input = screen.getByPlaceholderText(
      /Search the web/i
    ) as HTMLInputElement
    expect(tokens(input.className).some((t) => t === "pr-32" || t === "pr-36")).toBe(
      true
    )

    await gotoFetch()
    const fetchButton = screen.getByRole("button", {
      name: "Fetch",
      exact: true,
    })
    expect(fetchButton.querySelector("svg")).not.toBeNull()
    expect(fetchButton.textContent?.trim()).toBe("Fetch")
  })

  it("PG-S3 Search composer box + divider + footer gating intact (Search only)", async () => {
    renderWithBackend()
    await readyForSearch()

    const composer = screen.getByTestId("search-composer")
    expect(composer.className).toContain("bg-[var(--elevated)]")
    expect(tokens(composer.className)).toContain("rounded-xl")
    expect(composer.className).not.toContain("focus-within:")
    expect(
      composer.contains(screen.getByPlaceholderText(/Search the web/i))
    ).toBe(true)
    const footer = screen.getByTestId("search-composer-footer")
    expect(composer.contains(footer)).toBe(true)
    expect(
      within(footer).getByRole("button", {
        name: /python async search aggregator/i,
      })
    ).toBeInTheDocument()
    expect(within(footer).getByRole("combobox")).toBeInTheDocument()
    expect(
      within(footer).getByRole("spinbutton", { name: "Number of results" })
    ).toBeInTheDocument()
    expect(screen.queryByTestId("search-composer-divider")).not.toBeNull()

    await gotoFetch()
    expect(screen.queryByTestId("search-composer")).toBeNull()
    expect(screen.queryByTestId("search-composer-footer")).toBeNull()
  })

  it("PG-S4 per-card fetch survives (button + navigate/prefill + auto POST + doc)", async () => {
    const { stub } = renderWithBackend()
    await readyForSearch()

    const input = screen.getByPlaceholderText(
      /Search the web/i
    ) as HTMLInputElement
    fireEvent.change(input, { target: { value: "per-result fetch query" } })
    fireEvent.submit(input.closest("form")!)
    await waitFor(() => {
      expect(screen.getByText("Live backend result one")).toBeInTheDocument()
    })

    expect(screen.getByTestId("fetch-result-tavily-0")).toHaveAttribute(
      "title",
      "Fetch this page"
    )
    expect(screen.getByTestId("fetch-result-tavily-0")).toHaveAttribute(
      "aria-label",
      "Fetch Live backend result one"
    )

    fireEvent.click(screen.getByTestId("fetch-result-tavily-0"))

    await waitFor(() => {
      expect(screen.getByRole("tab", { name: "Fetch" })).toHaveAttribute(
        "aria-selected",
        "true"
      )
    })
    expect(
      screen.getByPlaceholderText(/URL to fetch/i) as HTMLInputElement
    ).toHaveValue("https://example.com/one")

    await waitFor(() => {
      expect(stub.requestsTo("/fetch")).toHaveLength(1)
    })
    expect(stub.requestsTo("/fetch")[0].body).toEqual({
      project_id: PLAYGROUND_PROJECT_ID,
      url: "https://example.com/one",
      max_chars: null,
      routing: { mode: "auto", providers: [], allow_fallback: true },
    })

    await waitFor(() => {
      expect(screen.getByText("Live document title")).toBeInTheDocument()
    })
    expect(screen.getByText(/Fetched markdown body/i)).toBeInTheDocument()
  })

  it("PG-S5 number contract intact (Results 6, no Depth, default limit 6 auto)", async () => {
    const { stub } = renderWithBackend()
    await readyForSearch()

    const footer = screen.getByTestId("search-composer-footer")
    const spin = within(footer).getByRole("spinbutton", {
      name: "Number of results",
    }) as HTMLInputElement
    expect(spin.getAttribute("type")).toBe("number")
    expect(spin).toHaveAttribute("min", "1")
    fireEvent.change(spin, { target: { value: "101" } })
    expect(spin).toHaveValue(100)
    fireEvent.change(spin, { target: { value: "6" } })
    expect(spin).toHaveAttribute("step", "1")
    expect(spin).toHaveValue(6)
    expect(footer.textContent).toMatch(/Results/)
    expect(screen.queryByRole("group", { name: /search depth/i })).toBeNull()

    const input = screen.getByPlaceholderText(
      /Search the web/i
    ) as HTMLInputElement
    fireEvent.change(input, { target: { value: "pg-s5 guard query" } })
    fireEvent.click(screen.getByRole("button", { name: "Search", exact: true }))

    await waitFor(() => {
      expect(stub.requestsTo("/search")).toHaveLength(1)
    })
    expect(stub.requestsTo("/search")[0].body).toEqual({
      project_id: PLAYGROUND_PROJECT_ID,
      query: "pg-s5 guard query",
      limit: 6,
      language: null,
      country_code: null,
      domains: [],
      routing: { mode: "auto", providers: [], allow_fallback: true },
    })
  })

  it("header, Simulator, and fetching logic untouched (Search-only diff)", async () => {
    renderWithBackend()
    await readyForSearch()
    expect(
      screen.getByRole("heading", { name: "Playground" })
    ).toBeInTheDocument()
    await gotoFetch()
    // Header persists across the Fetch hero/docked states.
    expect(
      screen.getByRole("heading", { name: "Playground" })
    ).toBeInTheDocument()

    // Fetching logic ownership (PLAN §3.5): the execution runners publish the
    // start/success/failure lifecycle through the slice (start still clears
    // the stale document up front); request mapping is unchanged.
    expect(executionSource).toContain("fetchStarted")
    expect(executionSource).toContain("fetchSucceeded")
    expect(executionSource).toContain("fetchFailed")
    expect(executionSource).toContain("searchStarted")
    expect(executionSource).toContain("searchSucceeded")
    expect(executionSource).toContain("searchFailed")
    expect(executionSource).toContain("useAppDispatch")
    expect(executionSource).toContain("url: request.url.trim()")
    expect(executionSource).toContain("max_chars: null")
    expect(executionSource).toMatch(
      /mode:\s*request\.providerId\s*\?\s*["']require["']\s*:\s*["']auto["']/
    )
    expect(contextSource).toContain("PolywebInner")
    // Playground fetch call contract untouched (markdown/4000 + trims).
    expect(playgroundSource).toContain('format: "markdown"')
    expect(playgroundSource).toContain("timeoutMs: 15000")
    expect(playgroundSource).toContain("fetchUrl.trim()")
    expect(playgroundSource).toContain("setFetchUrl")
    expect(playgroundSource).toContain("runFetch")
    // Search branch zero diff: reference seams still inline.
    expect(playgroundSource).toContain('data-testid="search-layout"')
    expect(playgroundSource).toContain('data-testid="search-composer"')
    expect(playgroundSource).toContain("hasSearchContent")
  })
})

describe("Slice 5 shim compatibility: shells re-export the feature owners", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("DashboardShell imports PlaygroundPage directly (SearchPlayground shim removed)", () => {
    expect(dashboardShellSource).toContain("PlaygroundPage")
    expect(dashboardShellSource).toContain("features/playground/ui/ProjectPlaygroundPage")
    expect(dashboardShellSource).not.toContain("components/search/SearchPlayground")
  })

})
})

describe("SearchPlayground.pg-s1.test.tsx", () => {

/**
 * PG-S1 Search empty state (Red).
 *
 * Plan contract under test:
 *   hasSearchContent = activeSearch !== null || isSearching || searchError !== null
 *   requestForm is the SAME element; only its wrapper toggles:
 *     idle    -> centered-hero (min-h ~55-60vh, max-w-3xl, vertically centered)
 *     docked  -> top-docked (form at top, results below)
 *   wrapper carries: transition-all duration-300 ease-out motion-reduce:transition-none
 *   Fetch tab / Search button / header / fetching flow are untouched.
 *   First-search-fails pins docked-top (error counts as content).
 *
 * Wrapper contract asserted here (Developer implements exactly this):
 *   <div data-testid="search-layout" data-state="hero|docked" class="...">
 *     {requestForm}
 *   </div>
 *
 * Every layout test below is Red against the current codebase: no
 * `search-layout` wrapper exists yet, so getByTestId throws.
 */

function renderWithBackend(
  searchHandler?: (req: { url: string }) => Response | Promise<Response>,
  fetchHandler?: (req: { url: string }) => Response | Promise<Response>
) {
  const stub = installFetchStub((req) => {
    const projectView = answerProjectProviders(req)
    if (projectView !== null) return projectView
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(allProvidersFixture())
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
    if (req.url === "/search" && req.method === "POST") {
      return searchHandler ? searchHandler(req) : ok(searchResponseFixture())
    }
    if (req.url === "/fetch" && req.method === "POST") {
      return fetchHandler ? fetchHandler(req) : ok(fetchResponseFixture())
    }
    return err(404, { detail: "unhandled test route" })
  })
  const view = render(
    <PlaygroundHarness />
  )
  return { stub, ...view }
}

async function readyForSearch() {
  await waitFor(() => {
    expect(
      screen.getByPlaceholderText(/Search the web/i)
    ).toBeInTheDocument()
  })
}

function submitQuery(query: string) {
  const input = screen.getByPlaceholderText(
    /Search the web/i
  ) as HTMLInputElement
  fireEvent.change(input, { target: { value: query } })
  fireEvent.submit(input.closest("form")!)
  return input
}

function expectTransitionClasses(wrapper: HTMLElement) {
  // Composer position and width stay fixed across request states.
  expect(wrapper).toHaveClass("top-docked", "w-full")
  expect(wrapper.className).not.toMatch(/min-h|max-w|justify-center|transition-all/)
}

describe("PG-S1 AC-PG-S1-1: idle search is a centered hero", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("shows the form with no results in a centered hero wrapper", async () => {
    renderWithBackend()
    await readyForSearch()

    // Form is present and empty-state shows no results or error.
    expect(
      screen.getByPlaceholderText(/Search the web/i)
    ).toBeInTheDocument()
    expect(screen.queryByText("Live backend result one")).not.toBeInTheDocument()
    expect(screen.queryByText(/no provider is configured/i)).not.toBeInTheDocument()

    const wrapper = screen.getByTestId("search-layout")
    expect(wrapper).toHaveAttribute("data-state", "docked")
    // Hero geometry: tall centered column, constrained width.
    expect(wrapper.className).not.toMatch(/min-h-\[(55|60)vh\]/)
    expect(wrapper.className).toContain("w-full")
    expectTransitionClasses(wrapper)
    // The request form is the wrapped content — same element, not a copy.
    expect(
      wrapper.querySelector('input[placeholder*="Search the web"]')
    ).not.toBeNull()
    // Hero must not carry the docked marker.
    expect(wrapper.className).toContain("top-docked")
  })
})

describe("PG-S1 AC-PG-S1-2: submit docks the form and keeps it docked while loading", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("docks on submit, stays docked while loading, results render below the form", async () => {
    const gate = deferred<Response>()
    renderWithBackend(() => gate.promise)
    await readyForSearch()

    const wrapperBefore = screen.getByTestId("search-layout")
    expect(wrapperBefore).toHaveAttribute("data-state", "docked")

    submitQuery("docking query")

    // Loading state pins docked-top BEFORE the network resolves
    // (hasSearchContent includes isSearching).
    await waitFor(() => {
      expect(screen.getByTestId("search-layout")).toHaveAttribute(
        "data-state",
        "docked"
      )
    })
    const loadingWrapper = screen.getByTestId("search-layout")
    expect(loadingWrapper.className).toContain("top-docked")
    expect(loadingWrapper.className).not.toMatch(/min-h-\[(55|60)vh\]/)
    expectTransitionClasses(loadingWrapper)
    // Button proves the pending state; form value is retained mid-flight.
    expect(
      screen.getByRole("button", { name: /Executing/i })
    ).toBeInTheDocument()
    expect(
      screen.getByPlaceholderText(/Search the web/i)
    ).toHaveValue("docking query")

    gate.resolve(ok(searchResponseFixture()))

    await waitFor(() => {
      expect(screen.getByText("Live backend result one")).toBeInTheDocument()
    })
    const dockedWrapper = screen.getByTestId("search-layout")
    expect(dockedWrapper).toHaveAttribute("data-state", "docked")
    expect(dockedWrapper.className).toContain("top-docked")
    expectTransitionClasses(dockedWrapper)

    // Results render BELOW the docked form in document order.
    const form = screen
      .getByPlaceholderText(/Search the web/i)
      .closest("form")!
    const firstResult = screen.getByText("Live backend result one")
    expect(
       
      form.compareDocumentPosition(firstResult) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy()
  })
})

describe("PG-S1 AC-PG-S1-3: errors pin docked-top; last-good results survive failure", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("first-search-failure docks the layout with the error and no results", async () => {
    renderWithBackend(() => err(503, { detail: "no provider is configured" }))
    await readyForSearch()

    submitQuery("doomed query")

    await waitFor(() => {
      expect(screen.getByText(/No provider is set up for this project/)).toBeInTheDocument()
    })
    // Error counts as content: the hero must be gone.
    const wrapper = screen.getByTestId("search-layout")
    expect(wrapper).toHaveAttribute("data-state", "docked")
    expect(wrapper.className).toContain("top-docked")
    expectTransitionClasses(wrapper)
    // Form survives the failure; results stay absent.
    expect(
      screen.getByPlaceholderText(/Search the web/i)
    ).toBeInTheDocument()
    expect(screen.queryByText("Live backend result one")).not.toBeInTheDocument()
  })

  it("success-then-failure keeps the last-good results docked beneath the form", async () => {
    let shouldFail = false
    renderWithBackend(() =>
      shouldFail
        ? err(503, { detail: "backend went away" })
        : ok(searchResponseFixture())
    )
    await readyForSearch()

    submitQuery("first query")
    await waitFor(() => {
      expect(screen.getByText("Live backend result one")).toBeInTheDocument()
    })
    expect(screen.getByTestId("search-layout")).toHaveAttribute(
      "data-state",
      "docked"
    )

    shouldFail = true
    submitQuery("second query")

    await waitFor(() => {
      expect(screen.getByText(/backend went away/i)).toBeInTheDocument()
    })
    // Last-good results are NOT cleared by the later failure.
    expect(screen.getByText("Live backend result one")).toBeInTheDocument()
    expect(screen.getByText("Live backend result two")).toBeInTheDocument()
    const wrapper = screen.getByTestId("search-layout")
    expect(wrapper).toHaveAttribute("data-state", "docked")
    expect(wrapper.className).toContain("top-docked")
    expectTransitionClasses(wrapper)
  })
})

describe("PG-S1 AC-PG-S1-4: smooth same-element transition retains focus and value", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("keeps the SAME form element, value, and focus across the hero->docked transition", async () => {
    renderWithBackend()
    await readyForSearch()

    const inputBefore = screen.getByPlaceholderText(
      /Search the web/i
    ) as HTMLInputElement
    const formBefore = inputBefore.closest("form")!
    const wrapperBefore = screen.getByTestId("search-layout")
    expectTransitionClasses(wrapperBefore)

    fireEvent.change(inputBefore, { target: { value: "focus retention query" } })
    inputBefore.focus()
    expect(inputBefore).toHaveFocus()
    fireEvent.submit(formBefore)

    await waitFor(() => {
      expect(screen.getByText("Live backend result one")).toBeInTheDocument()
    })

    const inputAfter = screen.getByPlaceholderText(
      /Search the web/i
    ) as HTMLInputElement
    const formAfter = inputAfter.closest("form")!
    // No remount: the form node identity is stable across the transition.
    expect(formAfter).toBe(formBefore)
    expect(inputAfter).toBe(inputBefore)
    // Value and focus survive the layout switch.
    expect(inputAfter).toHaveValue("focus retention query")
    expect(inputAfter).toHaveFocus()

    const wrapperAfter = screen.getByTestId("search-layout")
    expect(wrapperAfter).toHaveAttribute("data-state", "docked")
    expectTransitionClasses(wrapperAfter)
  })
})

describe("PG-S1 Fetch regression: header, button, and fetching flow are untouched", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("header, Search button, and the Fetch tab flow behave exactly as before", async () => {
    renderWithBackend()
    await readyForSearch()

    // Header untouched.
    expect(
      screen.getByRole("heading", { name: "Playground" })
    ).toBeInTheDocument()
    // Search submit button untouched (idle label).
    expect(
      screen.getByRole("button", { name: "Search", exact: true })
    ).toBeInTheDocument()

    // Fetching flow untouched end-to-end.
    fireEvent.click(screen.getByRole("tab", { name: "Fetch", exact: true }))
    const urlInput = screen.getByPlaceholderText(
      /URL to fetch/i
    ) as HTMLInputElement
    fireEvent.change(urlInput, { target: { value: "https://example.com/doc" } })
    fireEvent.submit(urlInput.closest("form")!)

    await waitFor(() => {
      expect(screen.getByText("Live document title")).toBeInTheDocument()
    })
    expect(screen.getByText(/Fetched markdown body/i)).toBeInTheDocument()
    // Fetch submit button returns to its idle label after completion.
    expect(
      screen.getByRole("button", { name: "Fetch", exact: true })
    ).toBeInTheDocument()
  })
})
})

describe("SearchPlayground.pg-s2.test.tsx", () => {

/**
 * PG-S2 Search-button breathing room (BDD Acceptance, RED phase).
 *
 * User bullet (verbatim): "Search button can use an icon and maybe more space
 * as it looks compressed". Read-only: .agents/FEEDBACK/UI/feedback.md L38.
 * SEE image-9.png: a small text-only "Search" pill with tight padding.
 *
 * Plan under test (ORCHESTRATOR RULING, polyweb-ui/ ONLY):
 *   - submit Button gets a LEADING lucide Search icon (size-3.5, aria-hidden)
 *     + inline-flex gap + the shared form size (h-8 px-4 gap-2);
 *   - input right-padding floor raised pr-28 -> pr-32/36 (no overlap with the
 *     wider button);
 *   - icon gated on mode === "search" ONLY; Fetch button stays text-only;
 *   - labels Search / Fetch / Executing... UNCHANGED;
 *   - PG-S1 hero/dock wrapper, header, Fetch/fetching flow untouched.
 *
 * AC mapping:
 *   AC-PG-S2-1  Search button keeps the exact accessible name "Search" with a
 *               leading lucide Search svg (size-3.5, aria-hidden so the icon
 *               contributes no accessible name; button textContent stays
 *               exactly "Search").
 *   AC-PG-S2-2  Icon is gated on mode === "search": svg present in Search
 *               mode, ZERO svg inside the Fetch submit button (Fetch text-only),
 *               and the icon returns when switching back to Search.
 *   AC-PG-S2-3  Button spacing: shared form size h-8 + px-4 + gap-2;
 *               the old px-4 / py-1.5 tokens are gone.
 *   AC-PG-S2-4  Input right-padding floor raised to pr-32 minimum (pr-32 or
 *               pr-36 accepted); pr-28 gone; structural no-overlap contract
 *               (relative wrapper + absolute right-0 button + w-full input
 *               with the raised floor). jsdom has no layout engine, so overlap
 *               is asserted structurally — same approach as S-P2-3.
 *   AC-PG-S2-5  Labels unchanged: idle "Search" / Fetch-mode "Fetch" /
 *               pending "Executing..." (exact strings).
 *   AC-PG-S2-6  Regressions (GREEN before and after): PG-S1 hero->docked
 *               wrapper contract, header copy, Fetch end-to-end flow,
 *               disabled-while-executing, icon-import allowlist
 *               (lucide-react only, no new icon deps).
 *
 * RED expectation: every AC-PG-S2-1..S2-4 assertion FAILS cleanly against the
 * current codebase (text-only px-4/py-1.5 button, pr-28 input, single prefix
 * <Search> usage). AC-PG-S2-5/6 stay GREEN throughout.
 */

const testDir = import.meta.dirname
// Slice 5 ownership: features/playground owns the playground UI (the
// SearchPlayground compat shell was removed in CLEANUP 1.1). Read the joined
// owner sources (same strength as the monolith read) plus DashboardShell for
// the shim-compat assert below.
const playgroundOwnerFiles = [
  "../model/usePlaygroundController.ts",
  "../model/playgroundFetchAction.ts",
  "../model/playgroundExecuteAction.ts",
  "../model/useResultPreview.ts",
  "../ui/PlaygroundPage.tsx",
  "../ui/SearchSection.tsx",
  "../ui/FetchSection.tsx",
  "../ui/SearchComposer.tsx",
  "../ui/SearchOptions.tsx",
  "../ui/FetchComposer.tsx",
  "../ui/SearchResults.tsx",
  "../ui/ResultCard.tsx",
  "../ui/ResultInspector.tsx",
  "../ui/WaterfallPanel.tsx",
  "../ui/FetchResult.tsx",
]
const playgroundSource = playgroundOwnerFiles
  .map((file) => readFileSync(path.resolve(testDir, file), "utf8"))
  .join("\n")
const dashboardShellSource = readFileSync(
  path.resolve(testDir, "../../../app/ProjectWorkspace.tsx"),
  "utf8"
)
const packageJson = JSON.parse(
  readFileSync(path.resolve(testDir, "../../../../package.json"), "utf8")
) as {
  dependencies?: Record<string, string>
  devDependencies?: Record<string, string>
}

function renderWithBackend(
  searchHandler?: (req: { url: string }) => Response | Promise<Response>,
  fetchHandler?: (req: { url: string }) => Response | Promise<Response>
) {
  const stub = installFetchStub((req) => {
    const projectView = answerProjectProviders(req)
    if (projectView !== null) return projectView
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(allProvidersFixture())
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
    if (req.url === "/search" && req.method === "POST") {
      return searchHandler ? searchHandler(req) : ok(searchResponseFixture())
    }
    if (req.url === "/fetch" && req.method === "POST") {
      return fetchHandler ? fetchHandler(req) : ok(fetchResponseFixture())
    }
    return err(404, { detail: "unhandled test route" })
  })
  const view = render(
    <PlaygroundHarness />
  )
  return { stub, ...view }
}

async function readyForSearch() {
  await waitFor(() => {
    expect(
      screen.getByPlaceholderText(/Search the web/i)
    ).toBeInTheDocument()
  })
}

function submitQuery(query: string) {
  const input = screen.getByPlaceholderText(
    /Search the web/i
  ) as HTMLInputElement
  fireEvent.change(input, { target: { value: query } })
  fireEvent.submit(input.closest("form")!)
  return input
}

const tokens = (className: string): string[] =>
  className.split(/\s+/).filter(Boolean)

describe("PG-S2 AC-PG-S2-1: Search button keeps its name with a leading aria-hidden icon", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("exposes role=button named exactly Search with a leading size-3.5 aria-hidden svg", async () => {
    renderWithBackend()
    await readyForSearch()

    // Accessible name survives the icon: exact match, no decoration.
    const button = screen.getByRole("button", { name: "Search", exact: true })
    expect(button).toBeInTheDocument()
    // The icon contributes no text: textContent is exactly the label.
    expect(button.textContent?.trim()).toBe("Search")

    // Leading lucide Search icon lives INSIDE the submit button
    // (not the input prefix icon, which sits outside the button).
    const svg = button.querySelector("svg")
    expect(svg).not.toBeNull()
    // Exact icon-size token (plan: size-3.5).
    expect(tokens(svg!.getAttribute("class") ?? "")).toContain("size-3.5")
    // Hidden from the a11y tree — directly or via an aria-hidden wrapper —
    // so the accessible name stays exactly "Search".
    const hidden =
      svg!.getAttribute("aria-hidden") === "true" ||
      svg!.closest('[aria-hidden="true"]') !== null
    expect(hidden).toBe(true)
    // Leading position: the svg precedes the "Search" text node.
    const html = button.innerHTML
    expect(html.indexOf("<svg")).toBeGreaterThanOrEqual(0)
    expect(html.indexOf("<svg")).toBeLessThan(html.indexOf("Search"))
  })

  it("references a second <Search> usage for the submit button in source", () => {
    // One <Search> is the input prefix icon; the plan adds a second one
    // inside the submit Button. Currently only the prefix exists.
    const usages = playgroundSource.match(/<Search[\s/>]/g) ?? []
    expect(usages.length).toBeGreaterThanOrEqual(2)
  })
})

describe("PG-S2 AC-PG-S2-2: icon gated on mode === search; Fetch stays text-only", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("shows the icon in Search mode, none in Fetch mode, and restores it on return", async () => {
    renderWithBackend()
    await readyForSearch()

    const searchButton = screen.getByRole("button", {
      name: "Search",
      exact: true,
    })
    expect(searchButton.querySelector("svg")).not.toBeNull()

    fireEvent.click(screen.getByRole("tab", { name: "Fetch", exact: true }))

    const fetchButton = screen.getByRole("button", {
      name: "Fetch",
      exact: true,
    })
    // Fetch text-only unchanged: no svg of any kind inside.
    expect(fetchButton.querySelector("svg")).not.toBeNull()
    expect(fetchButton.textContent?.trim()).toBe("Fetch")

    // Round-trip: back to Search restores the leading icon.
    fireEvent.click(screen.getByRole("tab", { name: "Search", exact: true }))
    const searchAgain = screen.getByRole("button", {
      name: "Search",
      exact: true,
    })
    expect(searchAgain.querySelector("svg")).not.toBeNull()
  })
})

describe("PG-S2 AC-PG-S2-3: submit uses the shared form button h-8 px-4 gap-2", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("carries the shared form size h-8 + px-4 + gap-2; px-5 / py-2 are gone", async () => {
    renderWithBackend()
    await readyForSearch()

    const button = screen.getByRole("button", { name: "Search", exact: true })
    const names = tokens(button.className)
    expect(names).toContain("h-8")
    expect(names).toContain("px-4")
    expect(names).toContain("gap-2")
    expect(names).not.toContain("px-5")
    expect(names).not.toContain("py-2")
    // Horizontal breathing room pairs with an inline-flex + gap layout.
    expect(names).toContain("inline-flex")
    expect(names.some((t) => /^gap-/.test(t))).toBe(true)
  })
})

describe("PG-S2 AC-PG-S2-4: input floor raised pr-32/36 with a no-overlap structure", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("raises the input right-padding floor to pr-32 minimum; pr-28 is gone", async () => {
    renderWithBackend()
    await readyForSearch()

    const input = screen.getByPlaceholderText(
      /Search the web/i
    ) as HTMLInputElement
    const names = tokens(input.className)
    expect(names.some((t) => t === "pr-32" || t === "pr-36")).toBe(true)
    expect(names).not.toContain("pr-28")
  })

  it("keeps the relative wrapper + absolute right-0 button + w-full input so text never slides under the wider button", async () => {
    renderWithBackend()
    await readyForSearch()

    const input = screen.getByPlaceholderText(
      /Search the web/i
    ) as HTMLInputElement
    // Full-bleed input inside a positioning context ...
    expect(tokens(input.className)).toContain("w-full")
    const relative = input.closest("div.relative")
    expect(relative).not.toBeNull()
    // ... with the submit button docked to the trailing edge ...
    const button = screen.getByRole("button", { name: "Search", exact: true })
    expect(relative!.contains(button)).toBe(true)
    const absolute = button.closest("div.absolute")
    expect(absolute).not.toBeNull()
    expect(tokens(absolute!.className)).toContain("right-0")
    // ... and the raised floor clearing the wider form button.
    const names = tokens(input.className)
    expect(names.some((t) => t === "pr-32" || t === "pr-36")).toBe(true)
  })
})

describe("PG-S2 AC-PG-S2-5: submit labels unchanged", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("idle Search, Fetch-mode Fetch, and pending Executing... use the exact strings", async () => {
    const gate = deferred<Response>()
    renderWithBackend(() => gate.promise)
    await readyForSearch()

    expect(
      screen.getByRole("button", { name: "Search", exact: true })
    ).toBeInTheDocument()

    fireEvent.click(screen.getByRole("tab", { name: "Fetch", exact: true }))
    expect(
      screen.getByRole("button", { name: "Fetch", exact: true })
    ).toBeInTheDocument()

    fireEvent.click(screen.getByRole("tab", { name: "Search", exact: true }))
    submitQuery("label lock query")

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Executing...", exact: true })
      ).toBeInTheDocument()
    })

    gate.resolve(ok(searchResponseFixture()))
    await waitFor(() => {
      expect(screen.getByText("Live backend result one")).toBeInTheDocument()
    })
    expect(
      screen.getByRole("button", { name: "Search", exact: true })
    ).toBeInTheDocument()
  })
})

describe("PG-S2 AC-PG-S2-6 regressions: PG-S1 hero/dock, header, Fetch flow, disabled state, icon allowlist", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("PG-S1 hero->docked wrapper contract is preserved", async () => {
    renderWithBackend()
    await readyForSearch()

    const hero = screen.getByTestId("search-layout")
    expect(hero).toHaveAttribute("data-state", "docked")
    expect(hero.className).not.toMatch(/min-h-\[(55|60)vh\]/)
    expect(hero.className).toContain("w-full")
    expect(hero.className).toContain("top-docked")

    submitQuery("regression dock query")

    await waitFor(() => {
      expect(screen.getByTestId("search-layout")).toHaveAttribute(
        "data-state",
        "docked"
      )
    })
    const docked = screen.getByTestId("search-layout")
    expect(docked.className).toContain("top-docked")
    await waitFor(() => {
      expect(screen.getByText("Live backend result one")).toBeInTheDocument()
    })
    // Header copy untouched.
    expect(
      screen.getByRole("heading", { name: "Playground" })
    ).toBeInTheDocument()
  })

  it("Fetch tab flow is untouched end-to-end", async () => {
    renderWithBackend()
    await readyForSearch()

    fireEvent.click(screen.getByRole("tab", { name: "Fetch", exact: true }))
    const urlInput = screen.getByPlaceholderText(
      /URL to fetch/i
    ) as HTMLInputElement
    fireEvent.change(urlInput, { target: { value: "https://example.com/doc" } })
    fireEvent.submit(urlInput.closest("form")!)

    await waitFor(() => {
      expect(screen.getByText("Live document title")).toBeInTheDocument()
    })
    expect(screen.getByText(/Fetched markdown body/i)).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "Fetch", exact: true })
    ).toBeInTheDocument()
  })

  it("submit stays disabled with Executing... while the request is in flight", async () => {
    const gate = deferred<Response>()
    renderWithBackend(() => gate.promise)
    await readyForSearch()

    submitQuery("disabled-state query")

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Executing...", exact: true })
      ).toBeDisabled()
    })

    gate.resolve(ok(searchResponseFixture()))
    await waitFor(() => {
      expect(screen.getByText("Live backend result one")).toBeInTheDocument()
    })
    expect(
      screen.getByRole("button", { name: "Search", exact: true })
    ).not.toBeDisabled()
  })

  it("icon comes from the lucide-react allowlist with no new icon dependency", () => {
    expect(playgroundSource).toMatch(/from\s+["']lucide-react["']/)
    expect(playgroundSource).toMatch(/import[\s\S]*\bSearch\b[\s\S]*from\s+["']lucide-react["']/)
    expect(playgroundSource).not.toMatch(/from\s+["']react-icons["']/)
    const allDeps = {
      ...(packageJson.dependencies ?? {}),
      ...(packageJson.devDependencies ?? {}),
    }
    expect(Object.keys(allDeps)).toContain("lucide-react")
    expect(Object.keys(allDeps)).not.toContain("react-icons")
  })
})

describe("Slice 5 shim compatibility: DashboardShell renders the canonical feature owner", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("imports PlaygroundPage from features/playground directly (SearchPlayground shim removed)", () => {
    expect(dashboardShellSource).toContain("PlaygroundPage")
    expect(dashboardShellSource).toContain("features/playground/ui/ProjectPlaygroundPage")
    expect(dashboardShellSource).not.toContain("components/search/SearchPlayground")
  })
})
})

describe("SearchPlayground.pg-s3.test.tsx", () => {

/**
 * PG-S3 Search-composer ChatGPT division aesthetic (BDD Acceptance, RED phase).
 *
 * User bullet (verbatim, feedback.md L40): "The centered search looks ok
 * (image-30) but it can look much better. (image-31) Like loooook at this
 * ChatGPT example, there is clear division. Once I enter something, it looks
 * like this (image-32). It moves down but we can of course keep ours at top.
 * But do you get the design aesthetic? That is the key. I feel like a loot
 * can be reused between the three. (See related: Simulator Page)"
 * Read-only: .agents/FEEDBACK/UI/feedback.md L40.
 * SEE images yourself: .agents/FEEDBACK/UI/image-30.png (OURS centered, bare
 * underline input, controls outside) + image-31.png (CHATGPT IDLE elevated
 * box, input row on top, footer tray below divider) + image-32.png
 * (CHATGPT USED separation, composer + results clearly divided).
 *
 * Plan under test (CONFIRMED, polyweb-ui/ ONLY):
 *   - search-composer box (elevated + border + rounded-xl + padding + shadow
 *     + focus-within signal, Search-mode ONLY, Fetch bare at PG-S3 time);
 *   - division idle + docked (results render AFTER the composer);
 *   - internal divider + footer tray (suggestions + provider + depth INSIDE
 *     the box, muted 13px);
 *   - focus-within + motion-reduce;
 *   - docked-top + same-form + PG-S1 contract intact;
 *   - PG-S2 button lock intact.
 *   - reusable pattern across three (Search now; Fetch/Simulator later --
 *     name seams only at PG-S3 time, NO shared file).
 *   - PG-F1 SUPERSEDES the no-shared-file rule: Fetch now goes via shared
 *     common/ComposerShell.tsx (testIdPrefix=fetch); Search stays the inline
 *     reference shape with zero migration.
 *
 * AC mapping:
 *   AC-PG-S3-1  Search-mode composer box: data-testid="search-composer"
 *               present ONLY in Search mode; carries elevated bg + border +
 *               rounded-xl + padding + shadow + focus-within signal; input
 *               inside is borderless (no bare underline); Fetch mode is bare
 *               of search-composer at PG-S3 time (PG-F1 later owns the shared
 *               ComposerShell extraction for Fetch; Search stays inline).
 *               Seam named in source, gated on mode === "search".
 *   AC-PG-S3-2  Division idle + docked: composer present in both states;
 *               after search, results render AFTER the composer in document
 *               order (clear division, ours stays docked-top per bullet).
 *   AC-PG-S3-3  Internal divider + footer tray: data-testid
 *               "search-composer-divider" + "search-composer-footer" live
 *               INSIDE the composer; Suggestions + Provider combobox + Depth
 *               group all live INSIDE the footer; footer is muted 13px
 *               (text-[13px] + text-[var(--muted)]); divider carries a
 *               border-t/divide/hr seam.
 *   AC-PG-S3-4  focus-within + motion-reduce: composer class carries a
 *               focus-within: signal token + transition + 
 *               motion-reduce:transition-none.
 *   AC-PG-S3-5  Regressions GREEN before/after: PG-S1 hero->docked wrapper
 *               contract (search-layout data-state, min-h-[55|60vh] +
 *               max-w-3xl hero vs top-docked, transition-all duration-300
 *               ease-out motion-reduce:transition-none), same-form identity
 *               across the transition, header copy, Fetch end-to-end flow.
 *   AC-PG-S3-6  Regressions GREEN before/after: PG-S2 button lock (Search
 *               button exact name + leading size-3.5 aria-hidden svg gated on
 *               Search ONLY, h-8 px-4 gap-2 shared form button, input pr-32/36 floor,
 *               labels Search/Fetch/Executing... unchanged).
 *
 * RED expectation: AC-PG-S3-1..S3-4 FAIL cleanly against the current
 * codebase (bare underline input with borderBottom style, controls OUTSIDE
 * any box, zero search-composer/divider/footer testids, zero focus-within:
 * on the form). AC-PG-S3-5/6 are composer-aware extensions of the PG-S1/S2
 * guards, so their composer-asserting cases are also RED; only the pure
 * header/Fetch-flow/Fetch-label guards inside S3-5/6 stay GREEN. The
 * committed PG-S1/PG-S2 files stay fully GREEN (17/17).
 */

const testDir = import.meta.dirname
// Slice 5 ownership: features/playground owns the playground UI (the
// SearchPlayground compat shell was removed in CLEANUP 1.1). Read the joined
// owner sources (same strength as the monolith read) plus DashboardShell for
// the shim-compat assert below.
const playgroundOwnerFiles = [
  "../model/usePlaygroundController.ts",
  "../model/playgroundFetchAction.ts",
  "../model/playgroundExecuteAction.ts",
  "../model/useResultPreview.ts",
  "../ui/PlaygroundPage.tsx",
  "../ui/SearchSection.tsx",
  "../ui/FetchSection.tsx",
  "../ui/SearchComposer.tsx",
  "../ui/SearchOptions.tsx",
  "../ui/FetchComposer.tsx",
  "../ui/SearchResults.tsx",
  "../ui/ResultCard.tsx",
  "../ui/ResultInspector.tsx",
  "../ui/WaterfallPanel.tsx",
  "../ui/FetchResult.tsx",
]
const playgroundSource = playgroundOwnerFiles
  .map((file) => readFileSync(path.resolve(testDir, file), "utf8"))
  .join("\n")
const dashboardShellSource = readFileSync(
  path.resolve(testDir, "../../../app/ProjectWorkspace.tsx"),
  "utf8"
)
const searchDir = path.resolve(testDir, "../../../components/search")

function renderWithBackend(
  searchHandler?: (req: { url: string }) => Response | Promise<Response>,
  fetchHandler?: (req: { url: string }) => Response | Promise<Response>
) {
  const stub = installFetchStub((req) => {
    const projectView = answerProjectProviders(req)
    if (projectView !== null) return projectView
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(allProvidersFixture())
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
    if (req.url === "/search" && req.method === "POST") {
      return searchHandler ? searchHandler(req) : ok(searchResponseFixture())
    }
    if (req.url === "/fetch" && req.method === "POST") {
      return fetchHandler ? fetchHandler(req) : ok(fetchResponseFixture())
    }
    return err(404, { detail: "unhandled test route" })
  })
  const view = render(
    <PlaygroundHarness />
  )
  return { stub, ...view }
}

async function readyForSearch() {
  await waitFor(() => {
    expect(
      screen.getByPlaceholderText(/Search the web/i)
    ).toBeInTheDocument()
  })
}

function submitQuery(query: string) {
  const input = screen.getByPlaceholderText(
    /Search the web/i
  ) as HTMLInputElement
  fireEvent.change(input, { target: { value: query } })
  fireEvent.submit(input.closest("form")!)
  return input
}

const tokens = (className: string): string[] =>
  className.split(/\s+/).filter(Boolean)

function expectComposerBoxClasses(composer: HTMLElement) {
  const cls = composer.className
  const names = tokens(cls)
  // Elevated surface.
  expect(cls).toContain("bg-[var(--elevated)]")
  // Border seam.
  expect(names).toContain("border")
  expect(cls).toContain("border-[var(--border-subtle)]")
  // Rounded-xl box (ChatGPT division aesthetic, not a pill, not square).
  expect(names).toContain("rounded-xl")
  // Padding: box pads its content (exact scale flexible, floor p-4).
  expect(names.some((t) => /^p-\d+$/.test(t))).toBe(true)
  // Shadow depth.
  expect(cls).toContain("shadow")
  // Focus-within signal: keyboard focus lights the box border/ring.
  expect(cls).not.toContain("focus-within:")
  expect(screen.getByRole("textbox", { name: "Search query" }).className).toContain("focus-visible:ring-2")
}

describe("PG-S3 AC-PG-S3-1: Search-mode composer box, Fetch stays bare, seams named with no shared file", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("renders an elevated bordered rounded-xl padded shadow box with focus-within signal in Search mode", async () => {
    renderWithBackend()
    await readyForSearch()

    const composer = screen.queryByTestId("search-composer")
    expect(composer).not.toBeNull()
    expectComposerBoxClasses(composer!)
    // The search input lives INSIDE the box (division aesthetic).
    const input = screen.getByPlaceholderText(/Search the web/i)
    expect(composer!.contains(input)).toBe(true)
    // Inside the box the input is borderless -- the box owns the border.
    // Current bare code styles the input itself with a bottom border.
    const inputEl = input as HTMLInputElement
    expect(inputEl.style.borderBottom).toBe("")
    expect((inputEl.getAttribute("style") ?? "").toLowerCase()).not.toContain(
      "border-bottom"
    )
  })

  it("keeps Fetch mode bare: no search-composer, fetch input + text-only Fetch button", async () => {
    renderWithBackend()
    await readyForSearch()

    fireEvent.click(screen.getByRole("tab", { name: "Fetch", exact: true }))

    const fetchInput = screen.getByPlaceholderText(/URL to fetch/i)
    expect(fetchInput).toBeInTheDocument()
    // Fetch does NOT adopt the search box (reusable pattern later, bare now).
    expect(screen.queryByTestId("search-composer")).toBeNull()
    expect(screen.queryByTestId("search-composer-footer")).toBeNull()
    const fetchButton = screen.getByRole("button", {
      name: "Fetch",
      exact: true,
    })
    expect(fetchButton.querySelector("svg")).not.toBeNull()
  })

  it("names the search seam in SearchPlayground source gated on Search mode (shared shell owned by PG-F1)", () => {
    // Seam names: Search inline reference; Fetch extraction owned by PG-F1.
    expect(playgroundSource).toContain("search-composer")
    expect(playgroundSource).toContain("search-composer-footer")
    expect(playgroundSource).toContain("search-composer-divider")
    // Gated on Search mode only.
    expect(playgroundSource).toMatch(/mode\s*===\s*["']search["']/)
    // PG-F1 owns common/ComposerShell.tsx — no PG-S3 ban. Search itself
    // must not be extracted into a separate file.
    const searchFiles: string[] = existsSync(searchDir)
      ? readdirSync(searchDir)
      : []
    expect(
      searchFiles.filter(
        (f) => /composer/i.test(f) && !/\.test\./.test(f)
      )
    ).toEqual([])
  })
})

describe("PG-S3 AC-PG-S3-2: clear division idle + docked, results after the composer", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("idle shows the composer with no results (hero, ChatGPT image-31 division)", async () => {
    renderWithBackend()
    await readyForSearch()

    const composer = screen.queryByTestId("search-composer")
    expect(composer).not.toBeNull()
    expect(
      screen.queryByText("Live backend result one")
    ).not.toBeInTheDocument()
    // Ours stays centered when idle (PG-S1 hero preserved under the box).
    expect(screen.getByTestId("search-layout")).toHaveAttribute(
      "data-state",
      "docked"
    )
  })

  it("docked keeps the composer on top with results BELOW it (ours docked-top, ChatGPT image-32 separation)", async () => {
    renderWithBackend()
    await readyForSearch()

    submitQuery("division query")

    await waitFor(() => {
      expect(screen.getByText("Live backend result one")).toBeInTheDocument()
    })
    const composer = screen.queryByTestId("search-composer")
    expect(composer).not.toBeNull()
    // Ours stays docked-top per bullet (never floats to bottom).
    expect(screen.getByTestId("search-layout")).toHaveAttribute(
      "data-state",
      "docked"
    )
    const firstResult = screen.getByText("Live backend result one")
    expect(composer!.compareDocumentPosition(firstResult)).toBeTruthy()
    // Results FOLLOW the composer in document order (clear division).
     
    expect(composer!.compareDocumentPosition(firstResult) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })
})

describe("PG-S3 AC-PG-S3-3: internal divider + footer tray owns suggestions/provider/number at muted 13px", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("places an internal divider seam inside the composer", async () => {
    renderWithBackend()
    await readyForSearch()

    const composer = screen.queryByTestId("search-composer")
    expect(composer).not.toBeNull()
    const divider = screen.queryByTestId("search-composer-divider")
    expect(divider).not.toBeNull()
    expect(composer!.contains(divider!)).toBe(true)
    // Divider seam: a horizontal rule token (border-t / divide- / hr).
    const tag = divider!.tagName.toLowerCase()
    const cls = divider!.className
    const isDividerSeam =
      tag === "hr" || cls.includes("border-t") || cls.includes("divide-")
    expect(isDividerSeam).toBe(true)
  })

  it("nests suggestions + provider + number INSIDE the footer tray at muted 13px", async () => {
    renderWithBackend()
    await readyForSearch()

    const composer = screen.queryByTestId("search-composer")
    expect(composer).not.toBeNull()
    const footer = screen.queryByTestId("search-composer-footer")
    expect(footer).not.toBeNull()
    expect(composer!.contains(footer!)).toBe(true)

    // All three controls live INSIDE the footer (ChatGPT tray aesthetic).
    // PG-S5: Depth SegmentedControl replaced by the Results number input.
    const suggestions = within(footer!).getByText(/^Suggestions$/i)
    expect(suggestions).toBeInTheDocument()
    const suggestionBtn = within(footer!).getByRole("button", {
      name: /python async search aggregator/i,
    })
    expect(suggestionBtn).toBeInTheDocument()
    const provider = within(footer!).getByRole("combobox")
    expect(provider).toBeInTheDocument()
    const count = within(footer!).getByRole("spinbutton", {
      name: "Number of results",
    }) as HTMLInputElement
    expect(count.getAttribute("type")).toBe("number")
    expect(count).toHaveAttribute("min", "1")
    fireEvent.change(count, { target: { value: "101" } })
    expect(count).toHaveValue(100)
    fireEvent.change(count, { target: { value: "6" } })
    expect(count).toHaveAttribute("step", "1")
    expect(count).toHaveValue(6)
    expect(footer!.textContent).toMatch(/Results/)
    expect(
      within(footer!).queryByRole("group", { name: /search depth/i })
    ).toBeNull()

    // Footer tray is muted 13px (secondary controls, not body copy).
    expect(footer!.className).toContain("text-[13px]")
    expect(footer!.className).toContain("text-[var(--muted)]")

    // Nothing leaks outside: the composer owns every instance.
    expect(
      screen.getByPlaceholderText(/Search the web/i).closest("form")
    ).not.toBeNull()
    const outsideSuggestions = Array.from(
      document.querySelectorAll("body *")
    ).filter(
      (el) =>
        el.textContent?.includes("Suggestions") &&
        !footer!.contains(el) &&
        el.textContent!.trim().startsWith("Suggestions")
    )
    expect(outsideSuggestions).toHaveLength(0)
  })
})

describe("PG-S3 AC-PG-S3-4: focus-within signal + motion-reduce on the composer", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("lights a focus-within signal ring/border and respects motion-reduce", async () => {
    renderWithBackend()
    await readyForSearch()

    const composer = screen.queryByTestId("search-composer")
    expect(composer).not.toBeNull()
    const cls = composer!.className
    // Focus signal fires from :focus-within, never a bare :focus on the box.
    expect(cls).not.toContain("focus-within:")
    expect(screen.getByRole("textbox", { name: "Search query" }).className).toContain("focus-visible:ring-2")
    expect(cls).not.toMatch(/(^|\s)focus:/)
    // Motion hygiene mirrors the PG-S1 layout wrapper.
    expect(tokens(cls)).toContain("transition-colors")
    expect(cls).toContain("motion-reduce:transition-none")
  })
})

describe("PG-S3 AC-PG-S3-5 regressions: docked-top + same-form + PG-S1 contract intact", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("keeps the PG-S1 hero->docked wrapper with the same form element under the composer", async () => {
    renderWithBackend()
    await readyForSearch()

    const hero = screen.getByTestId("search-layout")
    expect(hero).toHaveAttribute("data-state", "docked")
    expect(hero.className).not.toMatch(/min-h-\[(55|60)vh\]/)
    expect(hero.className).toContain("w-full")
    expect(hero.className).toContain("top-docked")
    for (const token of [
      "top-docked",
      "w-full",
    ]) {
      expect(hero.className).toContain(token)
    }
    const composerBefore = screen.queryByTestId("search-composer")
    expect(composerBefore).not.toBeNull()

    const inputBefore = screen.getByPlaceholderText(
      /Search the web/i
    ) as HTMLInputElement
    const formBefore = inputBefore.closest("form")!
    fireEvent.change(inputBefore, { target: { value: "s1 lock query" } })
    inputBefore.focus()
    fireEvent.submit(formBefore)

    await waitFor(() => {
      expect(screen.getByText("Live backend result one")).toBeInTheDocument()
    })
    const docked = screen.getByTestId("search-layout")
    expect(docked).toHaveAttribute("data-state", "docked")
    expect(docked.className).toContain("top-docked")
    // Same form element, value + focus survive (no remount for the box).
    const inputAfter = screen.getByPlaceholderText(
      /Search the web/i
    ) as HTMLInputElement
    expect(inputAfter.closest("form")).toBe(formBefore)
    expect(inputAfter).toHaveValue("s1 lock query")
    const composerAfter = screen.queryByTestId("search-composer")
    expect(composerAfter).not.toBeNull()
  })

  it("keeps header copy and the Fetch end-to-end flow untouched", async () => {
    renderWithBackend()
    await readyForSearch()

    expect(
      screen.getByRole("heading", { name: "Playground" })
    ).toBeInTheDocument()

    fireEvent.click(screen.getByRole("tab", { name: "Fetch", exact: true }))
    const urlInput = screen.getByPlaceholderText(
      /URL to fetch/i
    ) as HTMLInputElement
    fireEvent.change(urlInput, { target: { value: "https://example.com/doc" } })
    fireEvent.submit(urlInput.closest("form")!)

    await waitFor(() => {
      expect(screen.getByText("Live document title")).toBeInTheDocument()
    })
    expect(screen.getByText(/Fetched markdown body/i)).toBeInTheDocument()
  })
})

describe("PG-S3 AC-PG-S3-6 regressions: PG-S2 button lock intact inside the box", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("keeps the Search icon button spacing/floor/labels with the button inside the composer", async () => {
    const gate = deferred<Response>()
    renderWithBackend(() => gate.promise)
    await readyForSearch()

    const composer = screen.queryByTestId("search-composer")
    expect(composer).not.toBeNull()
    const button = screen.getByRole("button", { name: "Search", exact: true })
    expect(button.textContent?.trim()).toBe("Search")
    // Button lives INSIDE the composer box (top input row, not below).
    expect(composer!.contains(button)).toBe(true)
    const svg = button.querySelector("svg")
    expect(svg).not.toBeNull()
    expect(tokens(svg!.getAttribute("class") ?? "")).toContain("size-3.5")
    const hidden =
      svg!.getAttribute("aria-hidden") === "true" ||
      svg!.closest('[aria-hidden="true"]') !== null
    expect(hidden).toBe(true)

    const names = tokens(button.className)
    expect(names).toContain("h-8")
    expect(names).toContain("px-4")
    expect(names).toContain("gap-2")
    expect(names).not.toContain("px-5")
    expect(names).not.toContain("py-2")
    expect(names).toContain("inline-flex")

    const input = screen.getByPlaceholderText(
      /Search the web/i
    ) as HTMLInputElement
    const inputNames = tokens(input.className)
    expect(inputNames.some((t) => t === "pr-32" || t === "pr-36")).toBe(true)
    expect(inputNames).not.toContain("pr-28")

    fireEvent.change(input, { target: { value: "lock query" } })
    fireEvent.submit(input.closest("form")!)
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Executing...", exact: true })
      ).toBeDisabled()
    })
    gate.resolve(ok(searchResponseFixture()))
    await waitFor(() => {
      expect(screen.getByText("Live backend result one")).toBeInTheDocument()
    })
    expect(
      screen.getByRole("button", { name: "Search", exact: true })
    ).not.toBeDisabled()
  })

  it("Fetch submit stays text-only with exact labels", async () => {
    renderWithBackend()
    await readyForSearch()

    expect(
      screen.getByRole("button", { name: "Search", exact: true })
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole("tab", { name: "Fetch", exact: true }))
    const fetchButton = screen.getByRole("button", {
      name: "Fetch",
      exact: true,
    })
    expect(fetchButton.querySelector("svg")).not.toBeNull()
    expect(fetchButton.textContent?.trim()).toBe("Fetch")
  })
})

describe("Slice 5 shim compatibility: DashboardShell renders the canonical feature owner", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("imports PlaygroundPage from features/playground directly (SearchPlayground shim removed)", () => {
    expect(dashboardShellSource).toContain("PlaygroundPage")
    expect(dashboardShellSource).toContain("features/playground/ui/ProjectPlaygroundPage")
    expect(dashboardShellSource).not.toContain("components/search/SearchPlayground")
  })
})
})

describe("SearchPlayground.pg-s4.test.tsx", () => {

/**
 * PG-S4 per-result Fetch (BDD Acceptance, RED phase).
 *
 * User bullet (verbatim, feedback.md L42): "Currently to fetch a page from
 * search results, one must copy the URL, paste it in the fetch page's input
 * field and click on fetch. Can you make it more convenient? Like another
 * button for fetch for each field which when clicked navigates to the Fetch
 * tab, pastes the URL in the input field, and auto clicks fetch to load the
 * fetch results?"
 * Read-only: .agents/FEEDBACK/UI/feedback.md L42.
 * SEE image yourself: .agents/FEEDBACK/UI/image-11.png (results with only
 * external-link icon).
 *
 * Plan under test (CONFIRMED defaults, polyweb-ui/ ONLY):
 *   - icon-only FileText button per card (data-testid fetch-result-{id},
 *     title "Fetch this page", aria-label "Fetch {title}", disabled while
 *     executing, stopPropagation) + handleFetchResult (eligible-inherit else
 *     auto, setFetchUrl + switchMode fetch + direct runFetch markdown/4000ms).
 *
 * AC mapping:
 *   AC-PG-S4-1  Per-card button presence + external link intact: every result
 *               card exposes an icon-only FileText button with
 *               data-testid="fetch-result-{id}", title="Fetch this page",
 *               aria-label="Fetch {title}"; the existing external-link anchor
 *               (title "Open external link", href === url) is preserved.
 *   AC-PG-S4-2  Click navigates + prefills: clicking the per-card button
 *               selects the Fetch tab (aria-selected) and prefills the Fetch
 *               input with the result URL exact modulo surrounding-whitespace
 *               strip (consistent manual+context trim).
 *   AC-PG-S4-3  Auto-fetch happy path: click fires a single POST /fetch with
 *               the URL exact modulo surrounding-whitespace strip, shows
 *               "Executing..." while pending, then renders the fetched document
 *               (Live document title + markdown body).
 *   AC-PG-S4-4  Error case (+ success→failure clearing): fetch failure shows
 *               the error banner, retains the URL in the Fetch input, renders
 *               no stale document; a second fetch clears the prior doc at
 *               runFetch START (pending) and on terminal failure (production:
 *               clear activeFetch at START — covers pending + terminal).
 *               Whitespace URLs prefill trimmed + POST trimmed (consistent
 *               manual+context).
 *   AC-PG-S4-5  stopPropagation + disabled-while-executing: card selection is
 *               not triggered by the fetch button; per-card buttons are
 *               disabled while searching/fetching.
 *   AC-PG-S4-6  Provider eligible-inherit else auto + direct runFetch contract:
 *               fetch-eligible selection is inherited (require), ineligible
 *               resets to auto; runFetch uses format markdown + timeout 4000ms.
 *   AC-PG-S4-7  Regressions GREEN before/after: PG-S1 hero/docked + same-form,
 *               PG-S2 button lock, PG-S3 composer box + gating, shared
 *               ComposerShell owned by PG-F1 (no PG-S4 ban),
 *               SearchPlayground-only diff.
 *
 * RED expectation: AC-PG-S4-1..S4-6 FAIL cleanly against the current codebase
 * (zero fetch-result-* testids, single FileText usage, no handleFetchResult).
 * AC-PG-S4-7 stays GREEN throughout (committed PG-S1/S2/S3 guards).
 */

const testDir = import.meta.dirname
// Slice 5 ownership: features/playground owns the playground UI (the
// SearchPlayground compat shell was removed in CLEANUP 1.1). Read the joined
// owner sources (same strength as the monolith read) plus DashboardShell for
// the shim-compat assert below.
const playgroundOwnerFiles = [
  "../model/usePlaygroundController.ts",
  "../model/playgroundFetchAction.ts",
  "../model/playgroundExecuteAction.ts",
  "../model/useResultPreview.ts",
  "../ui/PlaygroundPage.tsx",
  "../ui/SearchSection.tsx",
  "../ui/FetchSection.tsx",
  "../ui/SearchComposer.tsx",
  "../ui/SearchOptions.tsx",
  "../ui/FetchComposer.tsx",
  "../ui/SearchResults.tsx",
  "../ui/ResultCard.tsx",
  "../ui/ResultInspector.tsx",
  "../ui/WaterfallPanel.tsx",
  "../ui/FetchResult.tsx",
]
const playgroundSource = playgroundOwnerFiles
  .map((file) => readFileSync(path.resolve(testDir, file), "utf8"))
  .join("\n")
const dashboardShellSource = readFileSync(
  path.resolve(testDir, "../../../app/ProjectWorkspace.tsx"),
  "utf8"
)
const searchDir = path.resolve(testDir, "../../../components/search")
const commonDir = path.resolve(testDir, "../../../components/common")
const packageJson = JSON.parse(
  readFileSync(path.resolve(testDir, "../../../../package.json"), "utf8")
) as {
  dependencies?: Record<string, string>
  devDependencies?: Record<string, string>
}

function renderWithBackend(
  searchHandler?: (req: { url: string }) => Response | Promise<Response>,
  fetchHandler?: (req: { url: string }) => Response | Promise<Response>
) {
  const stub = installFetchStub((req) => {
    const projectView = answerProjectProviders(req)
    if (projectView !== null) return projectView
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(allProvidersFixture())
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
    if (req.url === "/search" && req.method === "POST") {
      return searchHandler ? searchHandler(req) : ok(searchResponseFixture())
    }
    if (req.url === "/fetch" && req.method === "POST") {
      return fetchHandler ? fetchHandler(req) : ok(fetchResponseFixture())
    }
    return err(404, { detail: "unhandled test route" })
  })
  const view = render(
    <PlaygroundHarness />
  )
  return { stub, ...view }
}

async function readyForSearch() {
  await waitFor(() => {
    expect(
      screen.getByPlaceholderText(/Search the web/i)
    ).toBeInTheDocument()
  })
}

function submitQuery(query: string) {
  const input = screen.getByPlaceholderText(
    /Search the web/i
  ) as HTMLInputElement
  fireEvent.change(input, { target: { value: query } })
  fireEvent.submit(input.closest("form")!)
  return input
}

async function searchAndWait(query = "per-result fetch query") {
  submitQuery(query)
  await waitFor(() => {
    expect(screen.getByText("Live backend result one")).toBeInTheDocument()
  })
  expect(screen.getByText("Live backend result two")).toBeInTheDocument()
}

const tokens = (className: string): string[] =>
  className.split(/\s+/).filter(Boolean)

describe("PG-S4 AC-PG-S4-1: per-card icon-only Fetch button + external link intact", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("exposes one icon-only FileText fetch button per card with exact testid/title/aria-label", async () => {
    renderWithBackend()
    await readyForSearch()
    await searchAndWait()

    // Two results => exactly two per-card fetch buttons.
    const fetchButtons = document.querySelectorAll(
      '[data-testid^="fetch-result-"]'
    )
    expect(fetchButtons).toHaveLength(2)

    // Exact testids derive from the mapped result ids (tavily-0/tavily-1).
    const first = screen.getByTestId("fetch-result-tavily-0")
    const second = screen.getByTestId("fetch-result-tavily-1")
    expect(first).toBeInTheDocument()
    expect(second).toBeInTheDocument()

    // Contract per button: title + aria-label with the exact result title.
    expect(first).toHaveAttribute("title", "Fetch this page")
    expect(second).toHaveAttribute("title", "Fetch this page")
    expect(first).toHaveAttribute("aria-label", "Fetch Live backend result one")
    expect(second).toHaveAttribute(
      "aria-label",
      "Fetch Live backend result two"
    )

    // Icon-only: an svg inside, zero visible text.
    for (const btn of [first, second]) {
      expect(btn.querySelector("svg")).not.toBeNull()
      expect(btn.textContent?.trim()).toBe("")
    }

    // Buttons live inside their result cards (next to the external link).
    expect(
      first.closest("div")?.parentElement?.textContent ?? ""
    ).toContain("Live backend result one")
  })

  it("preserves the existing external-link anchor per card", async () => {
    renderWithBackend()
    await readyForSearch()
    await searchAndWait()

    // Fetch buttons exist AND external links are untouched.
    expect(screen.getByTestId("fetch-result-tavily-0")).toBeInTheDocument()
    const externals = document.querySelectorAll(
      'a[title="Open external link"]'
    )
    expect(externals).toHaveLength(2)
    const hrefs = Array.from(externals).map((a) =>
      a.getAttribute("href")
    )
    expect(hrefs).toContain("https://example.com/one")
    expect(hrefs).toContain("https://example.com/two")
    for (const a of Array.from(externals)) {
      expect(a).toHaveAttribute("target", "_blank")
      expect(a.querySelector("svg")).not.toBeNull()
    }
  })

  it("names the FileText per-card seam in source with disabled + stopPropagation + second FileText usage", () => {
    // Per-card seam tokens (all missing before PG-S4).
    expect(playgroundSource).toContain("fetch-result-")
    expect(playgroundSource).toContain("Fetch this page")
    expect(playgroundSource).toContain("handleFetchResult")
    // Second FileText usage: one is the Fetch-input prefix, one is per-card.
    const fileTextUsages = playgroundSource.match(/<FileText[\s/>]/g) ?? []
    expect(fileTextUsages.length).toBeGreaterThanOrEqual(2)
    // Disabled-while-executing on the per-card button.
    const fetchBtnIdx = playgroundSource.indexOf("fetch-result-")
    expect(fetchBtnIdx).toBeGreaterThanOrEqual(0)
    const fetchBtnWindow = playgroundSource.slice(fetchBtnIdx - 2000, fetchBtnIdx + 2000)
    expect(fetchBtnWindow).toContain("stopPropagation")
    expect(fetchBtnWindow).toMatch(/disabled\s*=\s*\{[^}]*isSearching[^}]*isFetching|disabled\s*=\s*\{[^}]*isFetching[^}]*isSearching/)
    // Icon allowlist unchanged: lucide-react only.
    expect(playgroundSource).toMatch(/from\s+["']lucide-react["']/)
    expect(playgroundSource).toMatch(/import[\s\S]*\bFileText\b[\s\S]*from\s+["']lucide-react["']/)
    const allDeps = {
      ...(packageJson.dependencies ?? {}),
      ...(packageJson.devDependencies ?? {}),
    }
    expect(Object.keys(allDeps)).toContain("lucide-react")
    expect(Object.keys(allDeps)).not.toContain("react-icons")
  })
})

describe("PG-S4 AC-PG-S4-2: click navigates to Fetch tab + prefills URL (exact modulo strip)", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("selects the Fetch tab and prefills the input with the clicked URL (exact modulo surrounding-whitespace strip)", async () => {
    renderWithBackend()
    await readyForSearch()
    await searchAndWait()

    fireEvent.click(screen.getByTestId("fetch-result-tavily-0"))

    // Fetch tab is now selected (Search unselected).
    await waitFor(() => {
      expect(screen.getByRole("tab", { name: "Fetch" })).toHaveAttribute(
        "aria-selected",
        "true"
      )
    })
    expect(screen.getByRole("tab", { name: "Search" })).toHaveAttribute(
      "aria-selected",
      "false"
    )

    // Input prefilled with the result URL exact modulo surrounding-whitespace
    // strip (consistent manual+context trim; clean fixture URLs stay identical).
    const urlInput = screen.getByPlaceholderText(
      /URL to fetch/i
    ) as HTMLInputElement
    expect(urlInput).toHaveValue("https://example.com/one")

    // Second card prefills its own URL independently.
    fireEvent.click(screen.getByRole("tab", { name: "Search", exact: true }))
    await waitFor(() => {
      expect(screen.getByText("Live backend result two")).toBeInTheDocument()
    })
    fireEvent.click(screen.getByTestId("fetch-result-tavily-1"))
    await waitFor(() => {
      expect(screen.getByRole("tab", { name: "Fetch" })).toHaveAttribute(
        "aria-selected",
        "true"
      )
    })
    expect(
      screen.getByPlaceholderText(/URL to fetch/i) as HTMLInputElement
    ).toHaveValue("https://example.com/two")
  })
})

describe("PG-S4 AC-PG-S4-3: auto-fetch POST + Executing + result render", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("auto-POSTs the URL (exact modulo strip, auto routing) and renders the fetched document", async () => {
    const { stub } = renderWithBackend()
    await readyForSearch()
    await searchAndWait()

    fireEvent.click(screen.getByTestId("fetch-result-tavily-0"))

    // Direct runFetch: single POST /fetch with the clicked URL, auto routing.
    await waitFor(() => {
      expect(stub.requestsTo("/fetch")).toHaveLength(1)
    })
    expect(stub.requestsTo("/fetch")[0].body).toEqual({
      project_id: PLAYGROUND_PROJECT_ID,
      url: "https://example.com/one",
      max_chars: null,
      routing: { mode: "auto", providers: [], allow_fallback: true },
    })

    // Result renders in the Fetch tab (markdown body + title).
    await waitFor(() => {
      expect(screen.getByText("Live document title")).toBeInTheDocument()
    })
    expect(screen.getByText(/Fetched markdown body/i)).toBeInTheDocument()
    // URL retained in the input after success.
    expect(
      screen.getByPlaceholderText(/URL to fetch/i) as HTMLInputElement
    ).toHaveValue("https://example.com/one")
  })

  it("shows Executing... disabled while the auto-fetch is in flight", async () => {
    const gate = deferred<Response>()
    const { stub } = renderWithBackend(undefined, () => gate.promise)
    await readyForSearch()
    await searchAndWait()

    fireEvent.click(screen.getByTestId("fetch-result-tavily-0"))

    // Pending state: POST issued, Fetch tab selected, submit disabled.
    await waitFor(() => {
      expect(stub.requestsTo("/fetch")).toHaveLength(1)
    })
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Executing...", exact: true })
      ).toBeInTheDocument()
    })
    expect(
      screen.getByRole("button", { name: "Executing...", exact: true })
    ).toBeDisabled()
    expect(
      screen.getByPlaceholderText(/URL to fetch/i) as HTMLInputElement
    ).toHaveValue("https://example.com/one")

    gate.resolve(ok(fetchResponseFixture()))
    await waitFor(() => {
      expect(screen.getByText("Live document title")).toBeInTheDocument()
    })
    expect(
      screen.getByRole("button", { name: "Fetch", exact: true })
    ).not.toBeDisabled()
  })
})

describe("PG-S4 AC-PG-S4-4: error banner + URL retained, no stale doc (+ clearing + trim)", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("shows the fetch error banner with the URL retained and no document", async () => {
    const { stub } = renderWithBackend(
      undefined,
      () => err(500, { detail: "fetch exploded" })
    )
    await readyForSearch()
    await searchAndWait()

    fireEvent.click(screen.getByTestId("fetch-result-tavily-1"))

    await waitFor(() => {
      expect(stub.requestsTo("/fetch")).toHaveLength(1)
    })
    expect(stub.requestsTo("/fetch")[0].body).toMatchObject({
      url: "https://example.com/two",
    })

    // Error banner with the exact backend detail.
    await waitFor(() => {
      expect(screen.getByText(/fetch exploded/i)).toBeInTheDocument()
    })
    // Fetch tab stays selected; URL is retained for retry.
    expect(screen.getByRole("tab", { name: "Fetch" })).toHaveAttribute(
      "aria-selected",
      "true"
    )
    expect(
      screen.getByPlaceholderText(/URL to fetch/i) as HTMLInputElement
    ).toHaveValue("https://example.com/two")
    // No stale document renders.
    expect(screen.queryByText("Live document title")).not.toBeInTheDocument()
    expect(screen.queryByText(/Fetched markdown body/i)).not.toBeInTheDocument()
  })

  it("clears the prior document while the second fetch pends and keeps it cleared on failure (success A -> deferred failure B)", async () => {
    const gate = deferred<Response>()
    let fetchCalls = 0
    const { stub } = renderWithBackend(undefined, () => {
      fetchCalls += 1
      if (fetchCalls === 1) return ok(fetchResponseFixture())
      return gate.promise
    })
    await readyForSearch()
    await searchAndWait()

    // Fetch A ok: document renders with A URL retained.
    fireEvent.click(screen.getByTestId("fetch-result-tavily-0"))
    await waitFor(() => {
      expect(stub.requestsTo("/fetch")).toHaveLength(1)
    })
    await waitFor(() => {
      expect(screen.getByText("Live document title")).toBeInTheDocument()
    })
    expect(
      screen.getByPlaceholderText(/URL to fetch/i) as HTMLInputElement
    ).toHaveValue("https://example.com/one")

    // Back to Search, then per-card fetch B (deferred failure).
    fireEvent.click(screen.getByRole("tab", { name: "Search", exact: true }))
    await waitFor(() => {
      expect(screen.getByText("Live backend result two")).toBeInTheDocument()
    })
    fireEvent.click(screen.getByTestId("fetch-result-tavily-1"))

    // Pending B: second POST issued, Executing..., input keeps B URL,
    // prior doc A is GONE at runFetch START (production clears activeFetch).
    await waitFor(() => {
      expect(stub.requestsTo("/fetch")).toHaveLength(2)
    })
    expect(stub.requestsTo("/fetch")[1].body).toMatchObject({
      url: "https://example.com/two",
    })
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Executing...", exact: true })
      ).toBeInTheDocument()
    })
    expect(
      screen.getByPlaceholderText(/URL to fetch/i) as HTMLInputElement
    ).toHaveValue("https://example.com/two")
    expect(screen.queryByText("Live document title")).not.toBeInTheDocument()
    expect(
      screen.queryByText(/Fetched markdown body/i)
    ).not.toBeInTheDocument()

    // Terminal failure: banner + B URL retained + still no document.
    gate.resolve(err(500, { detail: "second fetch exploded" }))
    await waitFor(() => {
      expect(
        screen.getByText(/second fetch exploded/i)
      ).toBeInTheDocument()
    })
    expect(screen.getByRole("tab", { name: "Fetch" })).toHaveAttribute(
      "aria-selected",
      "true"
    )
    expect(
      screen.getByPlaceholderText(/URL to fetch/i) as HTMLInputElement
    ).toHaveValue("https://example.com/two")
    expect(screen.queryByText("Live document title")).not.toBeInTheDocument()
    expect(
      screen.queryByText(/Fetched markdown body/i)
    ).not.toBeInTheDocument()
  })

  it("trims surrounding whitespace for prefill + POST (consistent manual+context)", async () => {
    const spacedUrl = "  https://example.com/spaced  "
    const trimmedUrl = "https://example.com/spaced"
    const { stub } = renderWithBackend(() =>
      ok(
        searchResponseFixture({
          query: "spaced",
          results: [
            {
              title: "Spaced title",
              url: spacedUrl,
              snippet: "spaced snippet",
              published_at: null,
              source: null,
              score: 0.9,
              metadata: {},
            },
          ],
          provider: "tavily",
          total_results: 1,
          usage: {
            provider: "tavily",
            operation: "search",
            units: "1",
            observed_at: "2026-09-06T10:02:00Z",
            request_id: "req-spaced",
            metadata: {},
            latency_ms: 100,
            status: "success",
          },
        })
      )
    )
    await readyForSearch()
    submitQuery("spaced query")
    await waitFor(() => {
      expect(screen.getByText("Spaced title")).toBeInTheDocument()
    })

    const btn = screen.getByTestId("fetch-result-tavily-0")
    expect(btn).toHaveAttribute("aria-label", "Fetch Spaced title")
    fireEvent.click(btn)

    await waitFor(() => {
      expect(stub.requestsTo("/fetch")).toHaveLength(1)
    })
    // POST trims (context trim) and prefill trims (handleFetchResult trim).
    expect(stub.requestsTo("/fetch")[0].body).toMatchObject({
      url: trimmedUrl,
    })
    expect(
      screen.getByPlaceholderText(/URL to fetch/i) as HTMLInputElement
    ).toHaveValue(trimmedUrl)

    await waitFor(() => {
      expect(screen.getByText("Live document title")).toBeInTheDocument()
    })
  })
})

describe("PG-S4 AC-PG-S4-5: stopPropagation + disabled while executing", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("does not select the card preview when the fetch button is clicked (stopPropagation)", async () => {
    renderWithBackend()
    await readyForSearch()
    await searchAndWait()

    // Precondition: first result is the selected preview after search.
    expect(screen.getByRole("heading", { name: "Result details" })).toBeInTheDocument()

    // Click the SECOND card's fetch button: navigates + fetches, must NOT
    // bubble to the card's onClick (which would select the second result).
    fireEvent.click(screen.getByTestId("fetch-result-tavily-1"))
    await waitFor(() => {
      expect(screen.getByText("Live document title")).toBeInTheDocument()
    })

    // Switch back to Search: preview must be cleared (empty inspector), not
    // the second result. A missing stopPropagation would leave tavily-1
    // selected because the card onClick runs after switchMode's clear.
    fireEvent.click(screen.getByRole("tab", { name: "Search", exact: true }))
    await waitFor(() => {
      expect(screen.getByText("Live backend result one")).toBeInTheDocument()
    })
    expect(screen.getByText("Select a result to see its details")).toBeInTheDocument()
    expect(screen.queryByRole("heading", { name: "Result details" })).not.toBeInTheDocument()
  })

  it("disables per-card fetch buttons while the next search is in flight (last-good results stay)", async () => {
    const gate = deferred<Response>()
    let calls = 0
    renderWithBackend(() => {
      calls += 1
      return calls === 1 ? ok(searchResponseFixture()) : gate.promise
    })
    await readyForSearch()
    await searchAndWait("first query")

    // Buttons enabled at rest.
    expect(screen.getByTestId("fetch-result-tavily-0")).not.toBeDisabled()
    expect(screen.getByTestId("fetch-result-tavily-1")).not.toBeDisabled()

    // Second search pends: last-good results stay, Executing shows, buttons lock.
    submitQuery("second query")
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Executing...", exact: true })
      ).toBeInTheDocument()
    })
    // Last-good results survive the pending second search.
    expect(screen.getByText("Live backend result one")).toBeInTheDocument()
    expect(screen.getByTestId("fetch-result-tavily-0")).toBeDisabled()
    expect(screen.getByTestId("fetch-result-tavily-1")).toBeDisabled()

    gate.resolve(ok(searchResponseFixture()))
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Search", exact: true })
      ).toBeInTheDocument()
    })
    expect(screen.getByTestId("fetch-result-tavily-0")).not.toBeDisabled()
  })
})

describe("PG-S4 AC-PG-S4-6: eligible-inherit else auto + markdown/4000ms contract", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("inherits a fetch-eligible provider (Firecrawl) with require routing", async () => {
    const { stub } = renderWithBackend()
    await readyForSearch()

    // Firecrawl is search+fetch: eligible in both modes. The catalog arrives
    // asynchronously, so open the picker and wait for its row before pinning it.
    const searchTrigger = await pinProvider("playground-search-provider", "Firecrawl")
    expect(searchTrigger.textContent).toContain("Firecrawl")

    await searchAndWait()
    fireEvent.click(screen.getByTestId("fetch-result-tavily-0"))

    await waitFor(() => {
      expect(stub.requestsTo("/fetch")).toHaveLength(1)
    })
    expect(stub.requestsTo("/fetch")[0].body).toEqual({
      project_id: PLAYGROUND_PROJECT_ID,
      url: "https://example.com/one",
      max_chars: null,
      routing: { mode: "require", providers: ["firecrawl"], allow_fallback: true },
    })
    // Provider selection survives the mode switch (still Firecrawl in Fetch).
    expect(screen.getByTestId("playground-fetch-provider").textContent).toContain(
      "Firecrawl"
    )
  })

  it("resets a fetch-ineligible provider (Brave search-only) to auto", async () => {
    const { stub } = renderWithBackend()
    await readyForSearch()

    // Brave is search-only: fetch-ineligible. The catalog arrives
    // asynchronously, so open the picker and wait for its row before pinning it.
    const searchTrigger = await pinProvider("playground-search-provider", "Brave Search")
    expect(searchTrigger.textContent).toContain("Brave Search")

    await searchAndWait()
    fireEvent.click(screen.getByTestId("fetch-result-tavily-0"))

    await waitFor(() => {
      expect(stub.requestsTo("/fetch")).toHaveLength(1)
    })
    expect(stub.requestsTo("/fetch")[0].body).toEqual({
      project_id: PLAYGROUND_PROJECT_ID,
      url: "https://example.com/one",
      max_chars: null,
      routing: { mode: "auto", providers: [], allow_fallback: true },
    })
    expect(
      screen.getByTestId("playground-fetch-provider").textContent
    ).toContain("Auto")
  })

  it("calls runFetch directly with markdown + 15000ms inside handleFetchResult", () => {
    const idx = playgroundSource.indexOf("handleFetchResult")
    expect(idx).toBeGreaterThanOrEqual(0)
    const tail = playgroundSource.slice(idx, idx + 8000)
    // Eligible-inherit else auto: consults fetch eligibility before runFetch.
    expect(tail).toMatch(/effectiveOperations\.includes\("fetch"\)/)
    // Direct runFetch with the Fetch-tab contract.
    expect(tail).toContain("setFetchUrl")
    expect(tail).toContain("runFetch")
    expect(tail).toMatch(/format:\s*.*"markdown"/)
    expect(tail).toMatch(/timeoutMs:\s*.*15000/)
    // Mode switch is part of the same handler (navigates to Fetch tab).
    expect(tail).toMatch(/switchMode\s*\(.*["']fetch["']|setMode\s*\(.*["']fetch["']/)
  })
})

describe("PG-S4 AC-PG-S4-7 regressions: PG-S1/S2/S3 guards + composer gating + file boundaries", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("PG-S1 hero->docked wrapper + same-form identity intact", async () => {
    renderWithBackend()
    await readyForSearch()

    const hero = screen.getByTestId("search-layout")
    expect(hero).toHaveAttribute("data-state", "docked")
    expect(hero.className).not.toMatch(/min-h-\[(55|60)vh\]/)
    expect(hero.className).toContain("w-full")
    expect(hero.className).toContain("top-docked")
    for (const token of [
      "top-docked",
      "w-full",
    ]) {
      expect(hero.className).toContain(token)
    }

    const inputBefore = screen.getByPlaceholderText(
      /Search the web/i
    ) as HTMLInputElement
    const formBefore = inputBefore.closest("form")!
    fireEvent.change(inputBefore, { target: { value: "s1 lock query" } })
    fireEvent.submit(formBefore)

    await waitFor(() => {
      expect(screen.getByText("Live backend result one")).toBeInTheDocument()
    })
    expect(screen.getByTestId("search-layout")).toHaveAttribute(
      "data-state",
      "docked"
    )
    expect(screen.getByTestId("search-layout").className).toContain(
      "top-docked"
    )
    const inputAfter = screen.getByPlaceholderText(
      /Search the web/i
    ) as HTMLInputElement
    expect(inputAfter.closest("form")).toBe(formBefore)
    expect(inputAfter).toHaveValue("s1 lock query")
    expect(
      screen.getByRole("heading", { name: "Playground" })
    ).toBeInTheDocument()
  })

  it("PG-S2 Search icon-button lock intact (exact name, leading svg, h-8/px-4/gap-2, pr-32 floor, labels)", async () => {
    const gate = deferred<Response>()
    renderWithBackend(() => gate.promise)
    await readyForSearch()

    const button = screen.getByRole("button", { name: "Search", exact: true })
    expect(button.textContent?.trim()).toBe("Search")
    const svg = button.querySelector("svg")
    expect(svg).not.toBeNull()
    expect(tokens(svg!.getAttribute("class") ?? "")).toContain("size-3.5")
    const hidden =
      svg!.getAttribute("aria-hidden") === "true" ||
      svg!.closest('[aria-hidden="true"]') !== null
    expect(hidden).toBe(true)

    const names = tokens(button.className)
    expect(names).toContain("h-8")
    expect(names).toContain("px-4")
    expect(names).toContain("gap-2")
    expect(names).not.toContain("px-5")
    expect(names).not.toContain("py-2")
    expect(names).toContain("inline-flex")

    const input = screen.getByPlaceholderText(
      /Search the web/i
    ) as HTMLInputElement
    const inputNames = tokens(input.className)
    expect(inputNames.some((t) => t === "pr-32" || t === "pr-36")).toBe(true)
    expect(inputNames).not.toContain("pr-28")

    fireEvent.change(input, { target: { value: "lock query" } })
    fireEvent.submit(input.closest("form")!)
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Executing...", exact: true })
      ).toBeDisabled()
    })
    gate.resolve(ok(searchResponseFixture()))
    await waitFor(() => {
      expect(screen.getByText("Live backend result one")).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole("tab", { name: "Fetch", exact: true }))
    const fetchButton = screen.getByRole("button", {
      name: "Fetch",
      exact: true,
    })
    expect(fetchButton.querySelector("svg")).not.toBeNull()
    expect(fetchButton.textContent?.trim()).toBe("Fetch")
  })

  it("PG-S3 composer box + divider + footer gating intact (Search only, Fetch bare)", async () => {
    renderWithBackend()
    await readyForSearch()

    // Search mode owns the composer box.
    const composer = screen.queryByTestId("search-composer")
    expect(composer).not.toBeNull()
    expect(composer!.className).toContain("bg-[var(--elevated)]")
    expect(tokens(composer!.className)).toContain("rounded-xl")
    expect(composer!.className).not.toContain("focus-within:")
    const input = screen.getByPlaceholderText(/Search the web/i)
    expect(composer!.contains(input)).toBe(true)
    const footer = screen.queryByTestId("search-composer-footer")
    expect(footer).not.toBeNull()
    expect(composer!.contains(footer!)).toBe(true)
    expect(
      within(footer!).getByRole("button", {
        name: /python async search aggregator/i,
      })
    ).toBeInTheDocument()
    expect(within(footer!).getByRole("combobox")).toBeInTheDocument()
    // PG-S5: Depth SegmentedControl replaced by the Results number input.
    const count = within(footer!).getByRole("spinbutton", {
      name: "Number of results",
    }) as HTMLInputElement
    expect(count.getAttribute("type")).toBe("number")
    expect(count).toHaveAttribute("min", "1")
    fireEvent.change(count, { target: { value: "101" } })
    expect(count).toHaveValue(100)
    fireEvent.change(count, { target: { value: "6" } })
    expect(count).toHaveAttribute("step", "1")
    expect(count).toHaveValue(6)
    expect(footer!.textContent).toMatch(/Results/)
    expect(
      within(footer!).queryByRole("group", { name: /search depth/i })
    ).toBeNull()
    expect(screen.queryByTestId("search-composer-divider")).not.toBeNull()

    // Fetch mode stays bare (reusable pattern later, no composer now).
    fireEvent.click(screen.getByRole("tab", { name: "Fetch", exact: true }))
    expect(screen.getByPlaceholderText(/URL to fetch/i)).toBeInTheDocument()
    expect(screen.queryByTestId("search-composer")).toBeNull()
    expect(screen.queryByTestId("search-composer-footer")).toBeNull()
  })

  it("names seams (shared shell owned by PG-F1) and Fetch flow untouched", async () => {
    // Seam names: Search inline reference; Fetch extraction owned by PG-F1.
    expect(playgroundSource).toContain("search-composer")
    expect(playgroundSource).toContain("search-composer-footer")
    expect(playgroundSource).toContain("search-composer-divider")
    expect(playgroundSource).toMatch(/mode\s*===\s*["']search["']/)
    // PG-F1 owns shared/ui/ComposerShell.tsx — no PG-S4 ban.
    const searchFiles: string[] = existsSync(searchDir)
      ? readdirSync(searchDir)
      : []
    expect(
      searchFiles.filter((f) => /composer/i.test(f) && !/\.test\./.test(f))
    ).toEqual([])

    // Fetch end-to-end flow untouched (manual path still works).
    renderWithBackend()
    await readyForSearch()
    fireEvent.click(screen.getByRole("tab", { name: "Fetch", exact: true }))
    const urlInput = screen.getByPlaceholderText(
      /URL to fetch/i
    ) as HTMLInputElement
    fireEvent.change(urlInput, { target: { value: "https://example.com/doc" } })
    fireEvent.submit(urlInput.closest("form")!)
    await waitFor(() => {
      expect(screen.getByText("Live document title")).toBeInTheDocument()
    })
    expect(screen.getByText(/Fetched markdown body/i)).toBeInTheDocument()
  })

  it("SearchPlayground-only diff: fetch-result seam lives only in SearchPlayground", () => {
    // The per-result seam must not leak into shared chrome or services.
    // Slice 4 ownership: canonical tabs live in shared/ui (the common/
    // compat shell was removed in CLEANUP 1.1). Read the joined owners
    // (same strength) for the seam assert below.
    expect(playgroundSource).toContain("search-composer")
    const pillTabsSource = [
      "../../../shared/ui/PillTabs.tsx",
      "../../../shared/ui/PillTabsList.tsx",
      "../../../shared/ui/PillTabsPanel.tsx",
      "../../../shared/ui/PillTabsContext.ts",
    ]
      .map((file) => readFileSync(path.resolve(testDir, file), "utf8"))
      .join("\n")
    expect(pillTabsSource).not.toContain("fetch-result-")
    expect(pillTabsSource).not.toContain("handleFetchResult")
    // Compat shell removed (CLEANUP 1.1): the canonical sources carry the switcher.
    expect(existsSync(path.resolve(testDir, "../../../components/common/PillTabs.tsx"))).toBe(false)
    expect(pillTabsSource).toContain("PillTabs")
    // No shared fetch-result component file was introduced.
    const searchFiles: string[] = existsSync(searchDir)
      ? readdirSync(searchDir)
      : []
    expect(
      searchFiles.filter(
        (f) => /fetch-?result/i.test(f) && !/\.test\./.test(f)
      )
    ).toEqual([])
    const commonFiles: string[] = existsSync(commonDir)
      ? readdirSync(commonDir)
      : []
    expect(commonFiles.filter((f) => /fetch-?result/i.test(f))).toEqual([])
  })
})

describe("Slice 5 shim compatibility: DashboardShell renders the canonical feature owner", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("imports PlaygroundPage from features/playground directly (SearchPlayground shim removed)", () => {
    expect(dashboardShellSource).toContain("PlaygroundPage")
    expect(dashboardShellSource).toContain("features/playground/ui/ProjectPlaygroundPage")
    expect(dashboardShellSource).not.toContain("components/search/SearchPlayground")
  })
})
})

describe("SearchPlayground.pg-s5.test.tsx", () => {

/**
 * PG-S5 number-of-results (BDD Acceptance, RED phase).
 *
 * User bullet (verbatim, feedback.md L44): "Instead of depth, let's just
 * have a number field as to the number of search results."
 * Read-only: .agents/FEEDBACK/UI/feedback.md L44.
 * SEE image yourself: .agents/FEEDBACK/UI/image-25.png (Provider dropdown +
 * Depth Fast/Balanced/Deep).
 *
 * Plan under test (CONFIRMED, default 6 preserves today, polyweb-ui/ ONLY):
 *   - SearchPlayground: delete depth consts/state/SegmentedControl usage,
 *     add resultCount state default 6, footer Depth row -> labeled number
 *     input (Results:, type number min1 max100 step1, aria Number of
 *     results), handleExecute passes maxResults: resultCount no mode;
 *   - types/polyweb SearchRequest drops mode;
 *   - PolywebContext runSearch routing.mode ->
 *     providerIds.length>0 ? require : auto (prefer dies); clampLimit
 *     unchanged.
 *   - Do NOT delete shared SegmentedControl.tsx.
 *
 * Known churn (NOT regressions — update to the number contract):
 *   c2 Depth-SegmentedControl, pg-s3 footer-depth, pg-s4 L784 footer group,
 *   PolywebContext mode matrix.
 *
 * AC mapping:
 *   AC-PG-S5-1  Footer number contract: search-composer-footer owns a
 *               labeled Results spinbutton (role spinbutton, accessible
 *               name "Number of results", type number, min 1, max 100,
 *               step 1, default value 6); the Depth SegmentedControl group
 *               (role group "Search depth", Fast/Balanced/Deep buttons) is
 *               gone; Provider combobox stays in the footer; Fetch mode
 *               stays bare (no spinbutton, no composer).
 *   AC-PG-S5-2  Wiring contract (FINAL REVIEW: real user submits — Search
 *               button click via userEvent, plus one Enter-key case):
 *               default POST /search carries limit 6 (auto when provider
 *               auto, require when pinned); editing the count to 25 sends
 *               limit 25; 0/200/empty/decimal-2.7 clamp to 1/100/1/2 via
 *               the unchanged clampLimit; no request ever carries
 *               routing.mode prefer. NOTE: click/Enter submits exercise
 *               native number validation, so the clamp cases REQUIRE the
 *               production formNoValidate fix (Developer, Search submit
 *               Button only) — they FAIL until it lands.
 *   AC-PG-S5-3  Source number contract: SearchPlayground owns resultCount
 *               + "Number of results" + maxResults: resultCount with zero
 *               depth seams and zero SegmentedControl usage; SearchRequest
 *               drops mode; PolywebContext routes require|auto with
 *               prefer dead and clampLimit intact; shared
 *               SegmentedControl.tsx is preserved.
 *   AC-PG-S5-4  Regressions GREEN before/after: PG-S4 per-card fetch
 *               (button + navigate/prefill + auto POST + doc render),
 *               composer seams (box/divider/footer/suggestions/provider),
 *               422 validation path (joined loc:msg banner, last-good
 *               intact).
 *
 * RED expectation: AC-PG-S5-1/2/3 FAIL cleanly against the current
 * codebase (zero spinbuttons, Depth group present with Balanced pressed,
 * SEARCH_DEPTH/searchDepth/SegmentedControl seams present, hardcoded
 * maxResults: 6 with mode: searchDepth, SearchRequest.mode present,
 * routing prefer branch present). AC-PG-S5-4 stays GREEN throughout.
 * FINAL REVIEW state (production number contract landed, formNoValidate
 * pending): AC-PG-S5-1/3 GREEN; AC-PG-S5-2 defaults/25/prefer GREEN;
 * clamp cases (0/200/empty/decimal) FAIL until Developer lands
 * formNoValidate on the Search submit Button.
 */

const testDir = import.meta.dirname
// Slice 5 ownership: features/playground owns the playground UI (the
// SearchPlayground compat shell was removed in CLEANUP 1.1). Read the joined
// owner sources (same strength as the monolith read) plus DashboardShell for
// the shim-compat assert below.
const playgroundOwnerFiles = [
  "../model/usePlaygroundController.ts",
  "../model/playgroundFetchAction.ts",
  "../model/playgroundExecuteAction.ts",
  "../model/useResultPreview.ts",
  "../ui/PlaygroundPage.tsx",
  "../ui/SearchSection.tsx",
  "../ui/FetchSection.tsx",
  "../ui/SearchComposer.tsx",
  "../ui/SearchOptions.tsx",
  "../ui/FetchComposer.tsx",
  "../ui/SearchResults.tsx",
  "../ui/ResultCard.tsx",
  "../ui/ResultInspector.tsx",
  "../ui/WaterfallPanel.tsx",
  "../ui/FetchResult.tsx",
]
const playgroundSource = playgroundOwnerFiles
  .map((file) => readFileSync(path.resolve(testDir, file), "utf8"))
  .join("\n")
const dashboardShellSource = readFileSync(
  path.resolve(testDir, "../../../app/ProjectWorkspace.tsx"),
  "utf8"
)
const typesSource = readFileSync(
  path.resolve(testDir, "../../../domains/execution/index.ts"),
  "utf8"
)
const executionTypesSource = readFileSync(
  path.resolve(testDir, "../../../domains/execution/model/types.ts"),
  "utf8"
)
const requestUtilsSource = readFileSync(path.resolve(testDir, "../../../domains/execution/model/requestUtils.ts"),"utf8");
const executionRunnerFiles = [
  "../../../domains/execution/state/useSearchRunner.ts",
  "../../../domains/execution/state/useFetchRunner.ts",
  "../../../domains/execution/state/ProjectExecutionProvider.tsx",
];
const executionStateSource = executionRunnerFiles
  .map((file) => readFileSync(path.resolve(testDir, file), "utf8"))
  .join("\n");const contextSource = readFileSync(
  path.resolve(testDir, "../../../context/PolywebContext.tsx"),
  "utf8"
)
// Slice 4 ownership: the canonical primitive lives in shared/ui (the common/
// compat shell was removed in CLEANUP 1.1). Read the owner (same strength);
// the shim-compat assert below guards the absence.
const segmentedPath = path.resolve(testDir, "../../../shared/ui/SegmentedControl.tsx")
const segmentedShimPath = path.resolve(testDir, "../../../components/common/SegmentedControl.tsx")

function renderWithBackend(
  searchHandler?: (req: { url: string }) => Response | Promise<Response>,
  fetchHandler?: (req: { url: string }) => Response | Promise<Response>
) {
  const stub = installFetchStub((req) => {
    const projectView = answerProjectProviders(req)
    if (projectView !== null) return projectView
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(allProvidersFixture())
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
    if (req.url === "/search" && req.method === "POST") {
      return searchHandler ? searchHandler(req) : ok(searchResponseFixture())
    }
    if (req.url === "/fetch" && req.method === "POST") {
      return fetchHandler ? fetchHandler(req) : ok(fetchResponseFixture())
    }
    return err(404, { detail: "unhandled test route" })
  })
  const view = render(
    <PlaygroundHarness />
  )
  return { stub, ...view }
}

async function readyForSearch() {
  await waitFor(() => {
    expect(
      screen.getByPlaceholderText(/Search the web/i)
    ).toBeInTheDocument()
  })
}

async function clickSearchButton(): Promise<void> {
  const user = userEvent.setup()
  await user.click(screen.getByRole("button", { name: "Search", exact: true }))
}

async function submitQueryViaClick(query: string) {
  const input = screen.getByPlaceholderText(
    /Search the web/i
  ) as HTMLInputElement
  fireEvent.change(input, { target: { value: query } })
  await clickSearchButton()
  return input
}

async function submitQueryViaEnter(query: string) {
  const user = userEvent.setup()
  const input = screen.getByPlaceholderText(
    /Search the web/i
  ) as HTMLInputElement
  await user.clear(input)
  await user.type(input, `${query}{Enter}`)
  return input
}

function resultsSpinInFooter(): HTMLElement {
  const footer = screen.getByTestId("search-composer-footer")
  return within(footer).getByRole("spinbutton", {
    name: "Number of results",
  })
}

describe("PG-S5 AC-PG-S5-1: footer Results number input replaces Depth", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("exposes a labeled Results spinbutton (number, min1 max100 step1, default 6) inside the composer footer", async () => {
    renderWithBackend()
    await readyForSearch()

    const composer = screen.getByTestId("search-composer")
    const footer = screen.getByTestId("search-composer-footer")
    expect(composer.contains(footer)).toBe(true)

    const spin = resultsSpinInFooter() as HTMLInputElement
    expect(spin).toBeInTheDocument()
    expect(composer.contains(spin)).toBe(true)
    expect(spin.getAttribute("type")).toBe("number")
    expect(spin).toHaveAttribute("min", "1")
    fireEvent.change(spin, { target: { value: "101" } })
    expect(spin).toHaveValue(100)
    fireEvent.change(spin, { target: { value: "6" } })
    expect(spin).toHaveAttribute("step", "1")
    expect(spin).toHaveValue(6)

    // Visible "Results" label lives in the same footer row.
    expect(footer.textContent).toMatch(/Results/)
  })

  it("removes the Depth SegmentedControl group (no search-depth group, no Fast/Balanced/Deep)", async () => {
    renderWithBackend()
    await readyForSearch()

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
    expect(
      within(footer).queryByRole("button", { name: "Fast", exact: true })
    ).toBeNull()
    expect(
      within(footer).queryByRole("button", { name: "Deep", exact: true })
    ).toBeNull()
    expect(within(footer).queryAllByRole("group")).toHaveLength(0)
  })

  it("keeps the Provider combobox intact inside the footer", async () => {
    renderWithBackend()
    await readyForSearch()

    const footer = screen.getByTestId("search-composer-footer")
    const trigger = within(footer).getByTestId("playground-search-provider")
    expect(trigger).toBeInTheDocument()
    expect(trigger).toHaveAccessibleName("Provider")
    expect(trigger.textContent).toContain("Auto")
    fireEvent.click(trigger)
    expect(
      await within(footer).findByRole("option", { name: "Auto" })
    ).toBeInTheDocument()
    expect(footer.textContent).toMatch(/Provider/)
  })

  it("keeps Fetch mode bare with no Results spinbutton and no composer", async () => {
    renderWithBackend()
    await readyForSearch()

    fireEvent.click(screen.getByRole("tab", { name: "Fetch", exact: true }))

    expect(
      screen.getByPlaceholderText(/URL to fetch/i)
    ).toBeInTheDocument()
    expect(screen.queryByTestId("search-composer")).toBeNull()
    expect(screen.queryByTestId("search-composer-footer")).toBeNull()
    expect(
      screen.queryByRole("spinbutton", { name: "Number of results" })
    ).toBeNull()
  })
})

describe("PG-S5 AC-PG-S5-2: /search limit + routing wiring", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("defaults to limit 6 with auto routing when the provider is auto", async () => {
    const { stub } = renderWithBackend()
    await readyForSearch()

    expect(resultsSpinInFooter() as HTMLInputElement).toHaveValue(6)

    await submitQueryViaClick("default count query")

    await waitFor(() => {
      expect(stub.requestsTo("/search")).toHaveLength(1)
    })
    expect(stub.requestsTo("/search")[0].body).toEqual({
      project_id: PLAYGROUND_PROJECT_ID,
      query: "default count query",
      limit: 6,
      language: null,
      country_code: null,
      domains: [],
      routing: { mode: "auto", providers: [], allow_fallback: true },
    })
  })

  it("defaults to limit 6 with require routing when a provider is pinned", async () => {
    const { stub } = renderWithBackend()
    await readyForSearch()

    // The catalog arrives asynchronously — open the picker and await the row.
    const searchTrigger = await pinProvider("playground-search-provider", "Tavily")
    expect(searchTrigger.textContent).toContain("Tavily")
    expect(resultsSpinInFooter() as HTMLInputElement).toHaveValue(6)

    await submitQueryViaClick("pinned default query")

    await waitFor(() => {
      expect(stub.requestsTo("/search")).toHaveLength(1)
    })
    expect(stub.requestsTo("/search")[0].body).toEqual({
      project_id: PLAYGROUND_PROJECT_ID,
      query: "pinned default query",
      limit: 6,
      language: null,
      country_code: null,
      domains: [],
      routing: { mode: "require", providers: ["tavily"], allow_fallback: true },
    })
  })

  it("sends the edited count (25) as limit", async () => {
    const { stub } = renderWithBackend()
    await readyForSearch()

    const spin = resultsSpinInFooter() as HTMLInputElement
    fireEvent.change(spin, { target: { value: "25" } })
    expect(spin).toHaveValue(25)

    await submitQueryViaClick("edited count query")

    await waitFor(() => {
      expect(stub.requestsTo("/search")).toHaveLength(1)
    })
    expect(stub.requestsTo("/search")[0].body).toEqual({
      project_id: PLAYGROUND_PROJECT_ID,
      query: "edited count query",
      limit: 25,
      language: null,
      country_code: null,
      domains: [],
      routing: { mode: "auto", providers: [], allow_fallback: true },
    })
  })

  it("clamps below-range 0 to limit 1", async () => {
    const { stub } = renderWithBackend()
    await readyForSearch()

    const spin = resultsSpinInFooter() as HTMLInputElement
    fireEvent.change(spin, { target: { value: "0" } })

    await submitQueryViaClick("clamp low query")

    await waitFor(() => {
      expect(stub.requestsTo("/search")).toHaveLength(1)
    })
    expect(stub.requestsTo("/search")[0].body).toMatchObject({ limit: 1 })
  })

  it("clamps above-range 200 to limit 100", async () => {
    const { stub } = renderWithBackend()
    await readyForSearch()

    const spin = resultsSpinInFooter() as HTMLInputElement
    fireEvent.change(spin, { target: { value: "200" } })

    await submitQueryViaClick("clamp high query")

    await waitFor(() => {
      expect(stub.requestsTo("/search")).toHaveLength(1)
    })
    expect(stub.requestsTo("/search")[0].body).toMatchObject({ limit: 100 })
  })

  it("clamps a cleared (empty) count to limit 1", async () => {
    const { stub } = renderWithBackend()
    await readyForSearch()

    const spin = resultsSpinInFooter() as HTMLInputElement
    fireEvent.change(spin, { target: { value: "" } })

    await submitQueryViaClick("clamp empty query")

    await waitFor(() => {
      expect(stub.requestsTo("/search")).toHaveLength(1)
    })
    expect(stub.requestsTo("/search")[0].body).toMatchObject({ limit: 1 })
  })

  it("truncates a decimal count (2.7) to limit 2 via Enter-key submit", async () => {
    const { stub } = renderWithBackend()
    await readyForSearch()

    const spin = resultsSpinInFooter() as HTMLInputElement
    fireEvent.change(spin, { target: { value: "2.7" } })

    await submitQueryViaEnter("clamp decimal query")

    await waitFor(() => {
      expect(stub.requestsTo("/search")).toHaveLength(1)
    })
    expect(stub.requestsTo("/search")[0].body).toMatchObject({ limit: 2 })
  })

  it("never emits prefer routing (auto or require only)", async () => {
    const { stub } = renderWithBackend()
    await readyForSearch()

    // Auto case.
    await submitQueryViaClick("prefer guard auto")
    await waitFor(() => {
      expect(stub.requestsTo("/search")).toHaveLength(1)
    })
    expect(stub.requestsTo("/search")[0].body).toMatchObject({
      routing: { mode: "auto", providers: [] },
    })

    // Pinned case must be require, never prefer.
    const pinnedTrigger = await pinProvider("playground-search-provider", "Tavily")
    expect(pinnedTrigger.textContent).toContain("Tavily")
    await submitQueryViaClick("prefer guard pinned")
    await waitFor(() => {
      expect(stub.requestsTo("/search")).toHaveLength(2)
    })
    expect(stub.requestsTo("/search")[1].body).toMatchObject({
      routing: { mode: "require", providers: ["tavily"] },
    })

    const modes = stub
      .requestsTo("/search")
      .map((r) => (r.body as { routing: { mode: string } }).routing.mode)
    expect(modes).toEqual(["auto", "require"])
    expect(modes).not.toContain("prefer")
  })
})

describe("PG-S5 AC-PG-S5-3: source number contract (playground/types/context)", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("SearchPlayground owns resultCount with Number of results and zero depth seams", () => {
    // Number contract tokens (all missing before PG-S5).
    expect(playgroundSource).toContain("resultCount")
    expect(playgroundSource).toContain("Number of results")
    expect(playgroundSource).toContain("<span>Results</span>")
    const numericFieldSource = readFileSync(path.resolve(testDir, "../../../shared/ui/NumericField.tsx"), "utf8")
    expect(numericFieldSource).toMatch(/type\s*=\s*["']number["']/)
    expect(playgroundSource).toMatch(/maxResults\s*:\s*resultCount/)

    // Depth contract fully deleted from the playground.
    expect(playgroundSource).not.toContain("SEARCH_DEPTH")
    expect(playgroundSource).not.toContain("searchDepth")
    expect(playgroundSource).not.toContain("Search depth")
    expect(playgroundSource).not.toContain("SegmentedControl")
    expect(playgroundSource).not.toContain("Depth:")
    expect(playgroundSource).not.toContain("mode: searchDepth")
  })

  it("execution SearchRequest drops mode (query + maxResults + timeoutMs only)", () => {
    const match = executionTypesSource.match(/interface SearchRequest \{[\s\S]*?\}/)
    expect(match).not.toBeNull()
    const block = match![0]
    expect(block).toContain("query: string")
    expect(block).toContain("maxResults: number")
    expect(block).toContain("timeoutMs: number")
    expect(block).not.toContain("mode")
    expect(block).not.toContain("fast")
    expect(block).not.toContain("balanced")
    expect(block).not.toContain("deep")
    expect(typesSource).toContain("SearchRequest")
  })

  it("PolywebContext routes require|auto with prefer dead and clampLimit intact", () => {
    // prefer dies: no prefer literal and no request.mode read remain.
    expect(contextSource).not.toContain('"prefer"')
    expect(contextSource).not.toContain("request.mode")
    // Number routing: pinned -> require, auto otherwise (canonical owner is
    // the execution domain; the context wires runSearch through).
    expect(executionStateSource).toMatch(
      /providerIds\.length\s*>\s*0\s*\?\s*["']require["']\s*:\s*["']auto["']/
    )
    expect(executionStateSource).toContain("runSearch")
    expect(contextSource).toContain("PolywebInner")
    // clampLimit is unchanged (still the 1..100 trunc guard) — canonical owner is the execution model; context wires it.
    expect(requestUtilsSource).toContain("function clampLimit")
    expect(requestUtilsSource).toContain("Math.min(100, Math.max(1")
    expect(executionStateSource).toContain("clampLimit")
  })

  it("playground search uses a 5000ms timeout budget (fetch uses 15000ms)", () => {
    const executeSource = readFileSync(
      path.resolve(testDir, "../model/playgroundExecuteAction.ts"),
      "utf8"
    )
    const searchBranch = executeSource.slice(
      executeSource.indexOf('if (mode === "search")'),
      executeSource.indexOf("} else {")
    )
    expect(searchBranch).toContain("timeoutMs: 5000")
    expect(searchBranch).not.toContain("timeoutMs: 3000")
    // Fetch contract untouched.
    expect(executeSource).toContain("timeoutMs: 15000")
  })

  it("preserves the shared SegmentedControl.tsx file (no deletion)", () => {
    expect(existsSync(segmentedPath)).toBe(true)
    const segmentedSource = readFileSync(segmentedPath, "utf8")
    expect(segmentedSource).toContain('role="group"')
    expect(segmentedSource).toContain("aria-pressed")
    expect(segmentedSource).toContain("SegmentedControl")
    // Compat shell removed (CLEANUP 1.1): only the shared primitive remains.
    expect(existsSync(segmentedShimPath)).toBe(false)
  })
})

describe("PG-S5 AC-PG-S5-4 regressions: per-card fetch + composer + 422", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("per-card fetch survives the number contract (button + navigate/prefill + auto POST + doc)", async () => {
    const { stub } = renderWithBackend()
    await readyForSearch()
    await submitQueryViaClick("per-result fetch query")
    await waitFor(() => {
      expect(screen.getByText("Live backend result one")).toBeInTheDocument()
    })

    expect(screen.getByTestId("fetch-result-tavily-0")).toHaveAttribute(
      "title",
      "Fetch this page"
    )
    expect(screen.getByTestId("fetch-result-tavily-0")).toHaveAttribute(
      "aria-label",
      "Fetch Live backend result one"
    )

    fireEvent.click(screen.getByTestId("fetch-result-tavily-0"))

    await waitFor(() => {
      expect(screen.getByRole("tab", { name: "Fetch" })).toHaveAttribute(
        "aria-selected",
        "true"
      )
    })
    expect(
      screen.getByPlaceholderText(/URL to fetch/i) as HTMLInputElement
    ).toHaveValue("https://example.com/one")

    await waitFor(() => {
      expect(stub.requestsTo("/fetch")).toHaveLength(1)
    })
    expect(stub.requestsTo("/fetch")[0].body).toEqual({
      project_id: PLAYGROUND_PROJECT_ID,
      url: "https://example.com/one",
      max_chars: null,
      routing: { mode: "auto", providers: [], allow_fallback: true },
    })

    await waitFor(() => {
      expect(screen.getByText("Live document title")).toBeInTheDocument()
    })
    expect(screen.getByText(/Fetched markdown body/i)).toBeInTheDocument()
  })

  it("composer seams stay intact (box + divider + footer + suggestions + provider)", async () => {
    renderWithBackend()
    await readyForSearch()

    const composer = screen.getByTestId("search-composer")
    expect(composer.className).toContain("bg-[var(--elevated)]")
    expect(composer.className).toContain("rounded-xl")
    expect(composer.className).not.toContain("focus-within:")

    const divider = screen.getByTestId("search-composer-divider")
    expect(composer.contains(divider)).toBe(true)
    expect(divider.tagName.toLowerCase()).toBe("hr")

    const footer = screen.getByTestId("search-composer-footer")
    expect(composer.contains(footer)).toBe(true)
    expect(footer.className).toContain("text-[13px]")
    expect(
      within(footer).getByRole("button", {
        name: /python async search aggregator/i,
      })
    ).toBeInTheDocument()
    expect(within(footer).getByRole("combobox")).toBeInTheDocument()

    expect(
      screen.getByRole("heading", { name: "Playground" })
    ).toBeInTheDocument()
  })

  it("422 validation surfaces the joined loc:msg banner with last-good results intact", async () => {
    let calls = 0
    renderWithBackend(() => {
      calls += 1
      if (calls === 1) return ok(searchResponseFixture())
      return err(422, {
        detail: [
          {
            loc: ["body", "limit"],
            msg: "Input should be less than or equal to 100",
          },
        ],
      })
    })
    await readyForSearch()

    await submitQueryViaClick("first good query")
    await waitFor(() => {
      expect(screen.getByText("Live backend result one")).toBeInTheDocument()
    })

    await submitQueryViaClick("second bad query")

    await waitFor(() => {
      expect(
        screen.getByText("body.limit: Input should be less than or equal to 100")
      ).toBeInTheDocument()
    })
    // Last-good results survive the validation failure.
    expect(screen.getByText("Live backend result one")).toBeInTheDocument()
    expect(screen.getByText("Live backend result two")).toBeInTheDocument()
  })
})

describe("Slice 5 shim compatibility: DashboardShell renders the canonical feature owner", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("imports PlaygroundPage from features/playground directly (SearchPlayground shim removed)", () => {
    expect(dashboardShellSource).toContain("PlaygroundPage")
    expect(dashboardShellSource).toContain("features/playground/ui/ProjectPlaygroundPage")
    expect(dashboardShellSource).not.toContain("components/search/SearchPlayground")
  })
})
})

describe("PlaygroundPage.persistence.test.tsx", () => {

/**
 * PLAN §4.2.6: component rehydration/remount/no-refetch coverage.
 *
 * - Seeded storage rehydrates drafts, options, mapped results, and error
 *   banners through PolywebProvider with zero /search|/fetch traffic.
 * - Fixture-backed runs survive a page remount under the same root store.
 * - A recreated root provider reloads completed state from localStorage
 *   through PersistGate without issuing /search|/fetch.
 * - Assertions stay on user-visible roles/placeholders/text; Redux internals
 *   are never inspected from component assertions.
 */

function persistedSearch(): SearchResponse {
  return {
    query: "seeded query",
    results: [
      {
        id: "brave-0",
        providerId: "brave",
        providerName: "Brave",
        title: "Seeded result title",
        url: "https://example.com/seeded",
        snippet: "Seeded snippet.",
        relevanceScore: 0.9,
      },
    ],
    totalResults: 1,
    selectedProviderId: "brave",
    fallbackChain: ["brave"],
    waterfall: [
      {
        providerId: "brave",
        providerName: "Brave",
        latencyMs: 187,
        status: "success",
        resultsCount: 1,
        costCredits: 1,
      },
    ],
    executionTimeMs: 187,
    costEstimateCredits: 1,
    timestamp: "2026-09-06T10:02:00.000Z",
  }
}

/** Mirrors the persistoid envelope: every field value serialized on its own. */
function seedStorage(state: Record<string, unknown>): void {
  const encoded: Record<string, string> = {}
  for (const [field, value] of Object.entries({
    ...initialPlaygroundState,
    ...state,
    _persist: { version: PLAYGROUND_PERSIST_VERSION, rehydrated: false },
  })) {
    encoded[field] = JSON.stringify(value)
  }
  window.localStorage.setItem(playgroundPersistKey(ADMIN_ACCOUNT_ID, PLAYGROUND_PROJECT_ID), JSON.stringify(encoded))
}

function stubBackend(
  searchHandler?: (req: { url: string }) => Response,
  fetchHandler?: (req: { url: string }) => Response
): FetchStub {
  return installFetchStub((req) => {
    const projectView = answerProjectProviders(req)
    if (projectView !== null) return projectView
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(allProvidersFixture())
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
    if (req.url === "/search" && req.method === "POST") {
      return searchHandler ? searchHandler(req) : ok(searchResponseFixture())
    }
    if (req.url === "/fetch" && req.method === "POST") {
      return fetchHandler ? fetchHandler(req) : ok(fetchResponseFixture())
    }
    return err(404, { detail: "unhandled test route" })
  })
}

function refuseNetwork(): FetchStub {
  return stubBackend(
    () => err(503, { detail: "refetch forbidden" }),
    () => err(503, { detail: "refetch forbidden" })
  )
}

async function submitSearch(query: string): Promise<void> {
  const input = await screen.findByPlaceholderText(/Search the web/i)
  fireEvent.change(input, { target: { value: query } })
  fireEvent.submit(input.closest("form")!)
}

async function openFetchTab(): Promise<void> {
  fireEvent.click(screen.getByRole("tab", { name: "Fetch", exact: true }))
  await screen.findByPlaceholderText(/URL to fetch/i)
}

async function submitFetch(url: string): Promise<void> {
  const input = await screen.findByPlaceholderText(/URL to fetch/i)
  fireEvent.change(input, { target: { value: url } })
  fireEvent.submit(input.closest("form")!)
}

describe("PlaygroundPage persistence", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("rehydrates drafts, options, results, and errors from storage without network execution", async () => {
    seedStorage({
      mode: "search",
      query: "seeded query",
      fetchUrl: "https://example.com/seeded-doc",
      selectedProviderId: "brave",
      resultCount: 25,
      activeSearch: persistedSearch(),
      activeFetch: null,
      searchStatus: "succeeded",
      fetchStatus: "failed",
      searchError: null,
      fetchError: "seeded fetch boom",
    })
    const stub = refuseNetwork()
    render(
      <PlaygroundHarness />
    )

    // Search tab: rehydrated draft, options, and mapped result.
    expect(await screen.findByPlaceholderText(/Search the web/i)).toHaveValue(
      "seeded query"
    )
    expect(screen.getByRole("spinbutton", { name: "Number of results" })).toHaveValue(25)
    // The provider catalog arrives asynchronously; the persisted pin only
    // displays once its entry exists. Picker rows exist only while open.
    const trigger = screen.getByTestId("playground-search-provider")
    await waitFor(() => {
      expect(trigger.textContent).toContain("Brave Search")
    })
    fireEvent.click(trigger)
    expect(
      await screen.findByRole("option", { name: "Brave Search" })
    ).toBeInTheDocument()
    expect(await screen.findByText("Seeded result title")).toBeInTheDocument()

    // Fetch tab: rehydrated URL draft and the persisted error banner.
    await openFetchTab()
    expect(screen.getByPlaceholderText(/URL to fetch/i)).toHaveValue(
      "https://example.com/seeded-doc"
    )
    expect(await screen.findByText("seeded fetch boom")).toBeInTheDocument()

    // Rehydration never executed a request.
    expect(stub.requestsTo("/search")).toHaveLength(0)
    expect(stub.requestsTo("/fetch")).toHaveLength(0)
  })

  it("keeps executed search and fetch state across a page remount with the same root store", async () => {
    const stub = stubBackend()
    const { rerender } = render(
      <PlaygroundHarness />
    )

    await submitSearch("remount probe")
    await screen.findByText("Live backend result one")
    await openFetchTab()
    await submitFetch("https://example.com/remount-doc")
    await screen.findByText("Parsed markdown")

    // Remount the page while the root provider (and its store) stays mounted.
    rerender(
      <span data-testid="interstitial" />
    )
    expect(await screen.findByTestId("interstitial")).toBeInTheDocument()
    rerender(
      <PlaygroundHarness />
    )

    // Fetch tab state survived (mode persisted as fetch).
    expect(await screen.findByPlaceholderText(/URL to fetch/i)).toHaveValue(
      "https://example.com/remount-doc"
    )
    expect(await screen.findByText("Parsed markdown")).toBeInTheDocument()

    // Search tab state survived too.
    fireEvent.click(screen.getByRole("tab", { name: "Search", exact: true }))
    expect(await screen.findByPlaceholderText(/Search the web/i)).toHaveValue(
      "remount probe"
    )
    expect(await screen.findByText("Live backend result one")).toBeInTheDocument()

    // One execution each — the remount issued no new request.
    expect(stub.requestsTo("/search")).toHaveLength(1)
    expect(stub.requestsTo("/fetch")).toHaveLength(1)
  })

  it("reloads executed state in a recreated provider from localStorage without refetching", async () => {
    const liveStub = stubBackend()
    const first = render(
      <PlaygroundHarness />
    )

    await submitSearch("reload probe")
    await screen.findByText("Live backend result one")

    // Wait for the bounded storage adapter to flush the completed run to disk.
    await waitFor(
      () => {
        expect(window.localStorage.getItem(playgroundPersistKey(ADMIN_ACCOUNT_ID, PLAYGROUND_PROJECT_ID)) ?? "").toContain(
          "reload probe"
        )
      },
      { timeout: 5000 }
    )
    first.unmount()

    // Fresh root provider (a browser reload): completed state must appear
    // through PersistGate with no /search or /fetch request.
    const stub = refuseNetwork()
    render(
      <PlaygroundHarness />
    )
    expect(await screen.findByPlaceholderText(/Search the web/i)).toHaveValue(
      "reload probe"
    )
    expect(await screen.findByText("Live backend result one")).toBeInTheDocument()
    expect(stub.requestsTo("/search")).toHaveLength(0)
    expect(stub.requestsTo("/fetch")).toHaveLength(0)
    expect(liveStub.requestsTo("/search")).toHaveLength(1)
  })
})
})
