import React from "react"
import { readFileSync, existsSync, readdirSync } from "node:fs"
import path from "node:path"
import { describe, it, expect, afterEach, vi } from "vitest"
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { PlaygroundPage as SearchPlayground } from "@/features/playground/ui/PlaygroundPage"
import { installFetchStub, ok, err, deferred } from "@/test/fetchMock"
import {
  allProvidersFixture,
  routingConfigFixture,
  dashboardFixture,
  searchResponseFixture,
  fetchResponseFixture,
} from "@/test/backendFixtures"

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
 * Plan under test (CONFIRMED defaults, freesearch-ui/ ONLY):
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
  "../../features/playground/model/usePlaygroundController.ts",
  "../../features/playground/model/playgroundFetchAction.ts",
  "../../features/playground/model/playgroundExecuteAction.ts",
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
const searchDir = testDir
const commonDir = path.resolve(testDir, "../common")
const packageJson = JSON.parse(
  readFileSync(path.resolve(testDir, "../../../package.json"), "utf8")
) as {
  dependencies?: Record<string, string>
  devDependencies?: Record<string, string>
}

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

function submitQuery(query: string) {
  const input = screen.getByPlaceholderText(
    /Search across all providers/i
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
      /Enter a URL to fetch/i
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
      screen.getByPlaceholderText(/Enter a URL to fetch/i) as HTMLInputElement
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
      screen.getByPlaceholderText(/Enter a URL to fetch/i) as HTMLInputElement
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
      screen.getByPlaceholderText(/Enter a URL to fetch/i) as HTMLInputElement
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
      screen.getByPlaceholderText(/Enter a URL to fetch/i) as HTMLInputElement
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
      screen.getByPlaceholderText(/Enter a URL to fetch/i) as HTMLInputElement
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
      screen.getByPlaceholderText(/Enter a URL to fetch/i) as HTMLInputElement
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
      screen.getByPlaceholderText(/Enter a URL to fetch/i) as HTMLInputElement
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
      screen.getByPlaceholderText(/Enter a URL to fetch/i) as HTMLInputElement
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
    expect(screen.getByText("Selected result")).toBeInTheDocument()

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
    expect(
      screen.getByText(
        /Select a search result from the list to inspect/i
      )
    ).toBeInTheDocument()
    expect(screen.queryByText("Selected result")).not.toBeInTheDocument()
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
    // asynchronously, so wait for its option before pinning it.
    await screen.findByRole("option", { name: "Firecrawl" })
    const searchSelect = screen.getByRole("combobox") as HTMLSelectElement
    fireEvent.change(searchSelect, { target: { value: "firecrawl" } })
    expect(searchSelect.value).toBe("firecrawl")

    await searchAndWait()
    fireEvent.click(screen.getByTestId("fetch-result-tavily-0"))

    await waitFor(() => {
      expect(stub.requestsTo("/fetch")).toHaveLength(1)
    })
    expect(stub.requestsTo("/fetch")[0].body).toEqual({
      url: "https://example.com/one",
      max_chars: null,
      routing: { mode: "require", providers: ["firecrawl"], allow_fallback: true },
    })
    // Provider selection survives the mode switch (still Firecrawl in Fetch).
    expect(
      screen.getByRole("combobox") as HTMLSelectElement
    ).toHaveValue("firecrawl")
  })

  it("resets a fetch-ineligible provider (Brave search-only) to auto", async () => {
    const { stub } = renderWithBackend()
    await readyForSearch()

    // Brave is search-only: fetch-ineligible. The catalog arrives
    // asynchronously, so wait for its option before pinning it.
    await screen.findByRole("option", { name: "Brave Search" })
    const searchSelect = screen.getByRole("combobox") as HTMLSelectElement
    fireEvent.change(searchSelect, { target: { value: "brave" } })
    expect(searchSelect.value).toBe("brave")

    await searchAndWait()
    fireEvent.click(screen.getByTestId("fetch-result-tavily-0"))

    await waitFor(() => {
      expect(stub.requestsTo("/fetch")).toHaveLength(1)
    })
    expect(stub.requestsTo("/fetch")[0].body).toEqual({
      url: "https://example.com/one",
      max_chars: null,
      routing: { mode: "auto", providers: [], allow_fallback: true },
    })
    expect(
      screen.getByRole("combobox") as HTMLSelectElement
    ).toHaveValue("auto")
  })

  it("calls runFetch directly with markdown + 4000ms inside handleFetchResult", () => {
    const idx = playgroundSource.indexOf("handleFetchResult")
    expect(idx).toBeGreaterThanOrEqual(0)
    const tail = playgroundSource.slice(idx, idx + 8000)
    // Eligible-inherit else auto: consults fetch eligibility before runFetch.
    expect(tail).toMatch(/isEligibleForOperation|fetchEnabled|capabilities/)
    // Direct runFetch with the Fetch-tab contract.
    expect(tail).toContain("setFetchUrl")
    expect(tail).toContain("runFetch")
    expect(tail).toMatch(/format:\s*.*"markdown"/)
    expect(tail).toMatch(/timeoutMs:\s*.*4000/)
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
    expect(hero).toHaveAttribute("data-state", "hero")
    expect(hero.className).toMatch(/min-h-\[(55|60)vh\]/)
    expect(hero.className).toContain("max-w-3xl")
    expect(hero.className).not.toContain("top-docked")
    for (const token of [
      "transition-all",
      "duration-300",
      "ease-out",
      "motion-reduce:transition-none",
    ]) {
      expect(hero.className).toContain(token)
    }

    const inputBefore = screen.getByPlaceholderText(
      /Search across all providers/i
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
      /Search across all providers/i
    ) as HTMLInputElement
    expect(inputAfter.closest("form")).toBe(formBefore)
    expect(inputAfter).toHaveValue("s1 lock query")
    expect(
      screen.getByRole("heading", { name: "Search Playground" })
    ).toBeInTheDocument()
  })

  it("PG-S2 Search icon-button lock intact (exact name, leading svg, px-5/py-2, pr-32 floor, labels)", async () => {
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
    expect(names).toContain("px-5")
    expect(names).toContain("py-2")
    expect(names).not.toContain("px-4")
    expect(names).not.toContain("py-1.5")
    expect(names).toContain("inline-flex")

    const input = screen.getByPlaceholderText(
      /Search across all providers/i
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
    expect(composer!.className).toContain("focus-within:")
    const input = screen.getByPlaceholderText(/Search across all providers/i)
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
    expect(count).toHaveAttribute("max", "100")
    expect(count).toHaveAttribute("step", "1")
    expect(count).toHaveValue(6)
    expect(footer!.textContent).toMatch(/Results:/)
    expect(
      within(footer!).queryByRole("group", { name: /search depth/i })
    ).toBeNull()
    expect(screen.queryByTestId("search-composer-divider")).not.toBeNull()

    // Fetch mode stays bare (reusable pattern later, no composer now).
    fireEvent.click(screen.getByRole("tab", { name: "Fetch", exact: true }))
    expect(screen.getByPlaceholderText(/Enter a URL to fetch/i)).toBeInTheDocument()
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
      /Enter a URL to fetch/i
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
      "../../shared/ui/PillTabs.tsx",
      "../../shared/ui/PillTabsList.tsx",
      "../../shared/ui/PillTabsPanel.tsx",
      "../../shared/ui/PillTabsContext.ts",
    ]
      .map((file) => readFileSync(path.resolve(testDir, file), "utf8"))
      .join("\n")
    expect(pillTabsSource).not.toContain("fetch-result-")
    expect(pillTabsSource).not.toContain("handleFetchResult")
    // Compat shell removed (CLEANUP 1.1): the canonical sources carry the switcher.
    expect(existsSync(path.resolve(testDir, "../common/PillTabs.tsx"))).toBe(false)
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
    expect(dashboardShellSource).toContain("features/playground/ui/PlaygroundPage")
    expect(dashboardShellSource).not.toContain("components/search/SearchPlayground")
  })
})
