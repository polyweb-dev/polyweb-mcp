import React from "react"
import { readFileSync, existsSync } from "node:fs"
import path from "node:path"
import { describe, it, expect, afterEach, vi } from "vitest"
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { PlaygroundPage as SearchPlayground } from "@/features/playground/ui/PlaygroundPage"
import { installFetchStub, ok, err } from "@/test/fetchMock"
import {
  allProvidersFixture,
  routingConfigFixture,
  dashboardFixture,
  searchResponseFixture,
  fetchResponseFixture,
} from "@/test/backendFixtures"

/**
 * PG-S5 number-of-results (BDD Acceptance, RED phase).
 *
 * User bullet (verbatim, feedback.md L44): "Instead of depth, let's just
 * have a number field as to the number of search results."
 * Read-only: .agents/FEEDBACK/UI/feedback.md L44.
 * SEE image yourself: .agents/FEEDBACK/UI/image-25.png (Provider dropdown +
 * Depth Fast/Balanced/Deep).
 *
 * Plan under test (CONFIRMED, default 6 preserves today, freesearch-ui/ ONLY):
 *   - SearchPlayground: delete depth consts/state/SegmentedControl usage,
 *     add resultCount state default 6, footer Depth row -> labeled number
 *     input (Results:, type number min1 max100 step1, aria Number of
 *     results), handleExecute passes maxResults: resultCount no mode;
 *   - types/freesearch SearchRequest drops mode;
 *   - FreeSearchContext runSearch routing.mode ->
 *     providerIds.length>0 ? require : auto (prefer dies); clampLimit
 *     unchanged.
 *   - Do NOT delete shared SegmentedControl.tsx.
 *
 * Known churn (NOT regressions — update to the number contract):
 *   c2 Depth-SegmentedControl, pg-s3 footer-depth, pg-s4 L784 footer group,
 *   FreeSearchContext mode matrix.
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
 *               drops mode; FreeSearchContext routes require|auto with
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
  "../../features/playground/model/usePlaygroundController.ts",
  "../../features/playground/model/playgroundFetchAction.ts",
  "../../features/playground/model/playgroundExecuteAction.ts",
  "../../features/playground/model/playgroundTypes.ts",
  "../../features/playground/model/useResultPreview.ts",
  "../../features/playground/ui/PlaygroundPage.tsx",
  "../../features/playground/ui/SearchSection.tsx",
  "../../features/playground/ui/FetchSection.tsx",
  "../../features/playground/ui/SearchComposer.tsx",
  "../../features/playground/ui/SearchOptions.tsx",
  "../../features/playground/ui/FetchComposer.tsx",
  "../../features/playground/ui/SearchResults.tsx",
  "../../features/playground/ui/ResultCard.tsx",
  "../../features/playground/ui/ResultInspector.tsx",
  "../../features/playground/ui/WaterfallPanel.tsx",
  "../../features/playground/ui/FetchResult.tsx",
]
const playgroundSource = playgroundOwnerFiles
  .map((file) => readFileSync(path.resolve(testDir, file), "utf8"))
  .join("\n")
const dashboardShellSource = readFileSync(
  path.resolve(testDir, "../../app/DashboardShell.tsx"),
  "utf8"
)
const typesSource = readFileSync(
  path.resolve(testDir, "../../domains/execution/index.ts"),
  "utf8"
)
const executionTypesSource = readFileSync(
  path.resolve(testDir, "../../domains/execution/model/types.ts"),
  "utf8"
)
const requestUtilsSource = readFileSync(path.resolve(testDir, "../../domains/execution/model/requestUtils.ts"),"utf8");
const executionRunnerFiles = [
  "../../domains/execution/state/useSearchRunner.ts",
  "../../domains/execution/state/useFetchRunner.ts",
];
const executionStateSource = executionRunnerFiles
  .map((file) => readFileSync(path.resolve(testDir, file), "utf8"))
  .join("\n");const contextSource = readFileSync(
  path.resolve(testDir, "../../context/FreeSearchContext.tsx"),
  "utf8"
)
// Slice 4 ownership: the canonical primitive lives in shared/ui (the common/
// compat shell was removed in CLEANUP 1.1). Read the owner (same strength);
// the shim-compat assert below guards the absence.
const segmentedPath = path.resolve(testDir, "../../shared/ui/SegmentedControl.tsx")
const segmentedShimPath = path.resolve(testDir, "../common/SegmentedControl.tsx")

function renderWithBackend(
  searchHandler?: (req: { url: string }) => Response | Promise<Response>,
  fetchHandler?: (req: { url: string }) => Response | Promise<Response>
) {
  const stub = installFetchStub((req) => {
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
    <FreeSearchProvider>
      <SearchPlayground />
    </FreeSearchProvider>
  )
  return { stub, ...view }
}

async function readyForSearch() {
  await waitFor(() => {
    expect(
      screen.getByPlaceholderText(/Search across all providers/i)
    ).toBeInTheDocument()
  })
}

async function clickSearchButton(): Promise<void> {
  const user = userEvent.setup()
  await user.click(screen.getByRole("button", { name: "Search", exact: true }))
}

async function submitQueryViaClick(query: string) {
  const input = screen.getByPlaceholderText(
    /Search across all providers/i
  ) as HTMLInputElement
  fireEvent.change(input, { target: { value: query } })
  await clickSearchButton()
  return input
}

async function submitQueryViaEnter(query: string) {
  const user = userEvent.setup()
  const input = screen.getByPlaceholderText(
    /Search across all providers/i
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
    expect(spin).toHaveAttribute("max", "100")
    expect(spin).toHaveAttribute("step", "1")
    expect(spin).toHaveValue(6)

    // Visible "Results:" label lives in the same footer row.
    expect(footer.textContent).toMatch(/Results:/)
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
    const select = within(footer).getByRole("combobox") as HTMLSelectElement
    expect(select).toBeInTheDocument()
    expect(select.value).toBe("auto")
    const options = Array.from(select.querySelectorAll("option")).map((o) =>
      o.textContent?.trim()
    )
    expect(options).toContain("Auto arbitration")
    expect(footer.textContent).toMatch(/Provider:/)
  })

  it("keeps Fetch mode bare with no Results spinbutton and no composer", async () => {
    renderWithBackend()
    await readyForSearch()

    fireEvent.click(screen.getByRole("tab", { name: "Fetch", exact: true }))

    expect(
      screen.getByPlaceholderText(/Enter a URL to fetch/i)
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

    const select = within(
      screen.getByTestId("search-composer-footer")
    ).getByRole("combobox") as HTMLSelectElement
    fireEvent.change(select, { target: { value: "tavily" } })
    expect(select.value).toBe("tavily")
    expect(resultsSpinInFooter() as HTMLInputElement).toHaveValue(6)

    await submitQueryViaClick("pinned default query")

    await waitFor(() => {
      expect(stub.requestsTo("/search")).toHaveLength(1)
    })
    expect(stub.requestsTo("/search")[0].body).toEqual({
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
    const select = within(
      screen.getByTestId("search-composer-footer")
    ).getByRole("combobox") as HTMLSelectElement
    fireEvent.change(select, { target: { value: "tavily" } })
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
    expect(playgroundSource).toContain("Results:")
    expect(playgroundSource).toMatch(/type\s*=\s*["']number["']/)
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

  it("FreeSearchContext routes require|auto with prefer dead and clampLimit intact", () => {
    // prefer dies: no prefer literal and no request.mode read remain.
    expect(contextSource).not.toContain('"prefer"')
    expect(contextSource).not.toContain("request.mode")
    // Number routing: pinned -> require, auto otherwise (canonical owner is
    // the execution domain; the context wires runSearch through).
    expect(executionStateSource).toMatch(
      /providerIds\.length\s*>\s*0\s*\?\s*["']require["']\s*:\s*["']auto["']/
    )
    expect(executionStateSource).toContain("runSearch")
    expect(contextSource).toContain("FreeSearchInner")
    // clampLimit is unchanged (still the 1..100 trunc guard) — canonical owner is the execution model; context wires it.
    expect(requestUtilsSource).toContain("function clampLimit")
    expect(requestUtilsSource).toContain("Math.min(100, Math.max(1")
    expect(executionStateSource).toContain("clampLimit")
  })

  it("playground search uses a 5000ms timeout budget (fetch stays 4000ms)", () => {
    const executeSource = readFileSync(
      path.resolve(testDir, "../../features/playground/model/playgroundExecuteAction.ts"),
      "utf8"
    )
    const searchBranch = executeSource.slice(
      executeSource.indexOf('if (mode === "search")'),
      executeSource.indexOf("} else {")
    )
    expect(searchBranch).toContain("timeoutMs: 5000")
    expect(searchBranch).not.toContain("timeoutMs: 3000")
    // Fetch contract untouched.
    expect(executeSource).toContain("timeoutMs: 4000")
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
      screen.getByPlaceholderText(/Enter a URL to fetch/i) as HTMLInputElement
    ).toHaveValue("https://example.com/one")

    await waitFor(() => {
      expect(stub.requestsTo("/fetch")).toHaveLength(1)
    })
    expect(stub.requestsTo("/fetch")[0].body).toEqual({
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
    expect(composer.className).toContain("focus-within:")

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
      screen.getByRole("heading", { name: "Search Playground" })
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
    expect(dashboardShellSource).toContain("features/playground/ui/PlaygroundPage")
    expect(dashboardShellSource).not.toContain("components/search/SearchPlayground")
  })
})
