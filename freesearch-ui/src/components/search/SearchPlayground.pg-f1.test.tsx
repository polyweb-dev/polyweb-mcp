import React from "react"
import { readFileSync, existsSync, readdirSync } from "node:fs"
import path from "node:path"
import { describe, it, expect, afterEach, vi } from "vitest"
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { SearchPlayground } from "./SearchPlayground"
import { installFetchStub, ok, err, deferred } from "@/test/fetchMock"
import {
  allProvidersFixture,
  routingConfigFixture,
  dashboardFixture,
  searchResponseFixture,
  fetchResponseFixture,
} from "@/test/backendFixtures"

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
 * Plan CONFIRMED under test (freesearch-ui/ ONLY):
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
// Slice 5 ownership: SearchPlayground.tsx and RouteSimulator.tsx are
// compatibility shells over features/playground and features/routing. Read
// the joined owner sources (same strength as the monolith reads) plus the
// shells for the shim-compat asserts below.
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
const playgroundShim = readFileSync(
  path.resolve(testDir, "./SearchPlayground.tsx"),
  "utf8"
)
const contextSource = readFileSync(
  path.resolve(testDir, "../../context/FreeSearchContext.tsx"),
  "utf8"
)
const executionSource = readFileSync(
  path.resolve(testDir, "../../domains/execution/state/ExecutionContext.tsx"),
  "utf8"
)
const simulatorOwnerFiles = [
  "../../features/routing/model/useSimulatorController.ts",
  "../../features/routing/ui/RouteSimulator.tsx",
  "../../features/routing/ui/SimulatorInputRow.tsx",
  "../../features/routing/ui/SimulatorFooter.tsx",
  "../../features/routing/ui/SimulatorPipeline.tsx",
  "../../features/routing/ui/PipelineStep.tsx",
  "../../features/routing/ui/ProviderStep.tsx",
  "../../features/routing/ui/FallbackCascade.tsx",
]
const simulatorSource = simulatorOwnerFiles
  .map((file) => readFileSync(path.resolve(testDir, file), "utf8"))
  .join("\n")
const simulatorShim = readFileSync(
  path.resolve(testDir, "../routing/RouteSimulator.tsx"),
  "utf8"
)
const commonDir = path.resolve(testDir, "../common")
const searchDir = testDir
// Slice 4 ownership: the canonical shell lives in shared/ui; common/
// keeps a compatibility shell. Read the owner (same strength) plus the
// shell for the shim-compat assert in the source test below.
const composerShellPath = path.resolve(testDir, "../../shared/ui/ComposerShell.tsx")
const composerShimPath = path.resolve(testDir, "../common/ComposerShell.tsx")

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

async function gotoFetch() {
  fireEvent.click(screen.getByRole("tab", { name: "Fetch", exact: true }))
  await waitFor(() => {
    expect(
      screen.getByPlaceholderText(/Enter a URL to fetch/i)
    ).toBeInTheDocument()
  })
}

async function readyForFetch() {
  await readyForSearch()
  await gotoFetch()
}

function submitFetchUrl(url: string) {
  const input = screen.getByPlaceholderText(
    /Enter a URL to fetch/i
  ) as HTMLInputElement
  fireEvent.change(input, { target: { value: url } })
  fireEvent.submit(input.closest("form")!)
  return input
}

const tokens = (className: string): string[] =>
  className.split(/\s+/).filter(Boolean)

function expectTransitionClasses(wrapper: HTMLElement) {
  expect(wrapper.className).toContain("transition-all")
  expect(wrapper.className).toContain("duration-300")
  expect(wrapper.className).toContain("ease-out")
  expect(wrapper.className).toContain("motion-reduce:transition-none")
}

function expectHeroGeometry(wrapper: HTMLElement) {
  expect(wrapper.className).toMatch(/min-h-\[(55|60)vh\]/)
  expect(wrapper.className).toContain("max-w-3xl")
  expect(wrapper.className).not.toContain("top-docked")
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
  expect(cls).toContain("focus-within:")
  expect(cls).toContain("signal")
}

describe("PG-F1 AC-PG-F1-1: idle Fetch is a centered hero (Fetch analogue of PG-S1)", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("shows the Fetch form with no doc/error in a centered hero fetch-layout", async () => {
    renderWithBackend()
    await readyForFetch()

    expect(
      screen.getByPlaceholderText(/Enter a URL to fetch/i)
    ).toBeInTheDocument()
    expect(screen.queryByText("Live document title")).not.toBeInTheDocument()
    expect(screen.queryByText(/Fetched markdown body/i)).not.toBeInTheDocument()

    const wrapper = screen.getByTestId("fetch-layout")
    expect(wrapper).toHaveAttribute("data-state", "hero")
    expectHeroGeometry(wrapper)
    expectTransitionClasses(wrapper)
    expect(
      wrapper.querySelector('input[placeholder*="Enter a URL to fetch"]')
    ).not.toBeNull()
    expect(wrapper.className).not.toContain("top-docked")
  })

  it("uses the SAME hero/transition tokens as search-layout", async () => {
    renderWithBackend()
    await readyForSearch()

    const searchHero = screen.getByTestId("search-layout")
    expect(searchHero).toHaveAttribute("data-state", "hero")
    const searchClasses = new Set(tokens(searchHero.className))

    await gotoFetch()

    const fetchHero = screen.getByTestId("fetch-layout")
    expect(fetchHero).toHaveAttribute("data-state", "hero")
    // Shared contract: identical transition + hero-geometry tokens.
    for (const token of [
      "transition-all",
      "duration-300",
      "ease-out",
      "motion-reduce:transition-none",
      "max-w-3xl",
      "mx-auto",
      "flex",
      "flex-col",
      "justify-center",
    ]) {
      expect(tokens(fetchHero.className)).toContain(token)
      expect(searchClasses.has(token)).toBe(true)
    }
    expect(fetchHero.className).toMatch(/min-h-\[(55|60)vh\]/)
    expect(searchHero.className).toMatch(/min-h-\[(55|60)vh\]/)
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
      "hero"
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
    expect(screen.getByPlaceholderText(/Enter a URL to fetch/i)).toHaveValue(
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
      .getByPlaceholderText(/Enter a URL to fetch/i)
      .closest("form")!
    const docTitle = screen.getByText("Live document title")
     
    expect(form.compareDocumentPosition(docTitle) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it("owns hasFetchContent as activeFetch||isFetching||fetchError gating fetch-layout", () => {
    expect(playgroundSource).toContain("hasFetchContent")
    expect(playgroundSource).toMatch(
      /hasFetchContent\s*=\s*activeFetch\s*!==\s*null\s*\|\|\s*isFetching\s*\|\|\s*fetchError\s*!==\s*null/
    )
    expect(playgroundSource).toContain("fetch-layout")
    expect(playgroundSource).toMatch(
      /hasFetchContent\s*\?\s*["']docked["']\s*:\s*["']hero["']|data-state\s*=\s*\{hasFetchContent/
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
      screen.getByPlaceholderText(/Enter a URL to fetch/i)
    ).toBeInTheDocument()
    expect(
      screen.getByPlaceholderText(/Enter a URL to fetch/i) as HTMLInputElement
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
      screen.getByPlaceholderText(/Enter a URL to fetch/i) as HTMLInputElement
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
      screen.getByPlaceholderText(/Enter a URL to fetch/i) as HTMLInputElement
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
      /Enter a URL to fetch/i
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
      /Enter a URL to fetch/i
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
    expect(composer.className).toContain("focus-within:border-[var(--signal)]/60")
    expect(composer.className).toContain("motion-reduce:transition-none")

    const input = screen.getByPlaceholderText(/Enter a URL to fetch/i)
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
    expect(footer.textContent).toMatch(/Provider:/)
    const select = within(footer).getByRole("combobox") as HTMLSelectElement
    expect(select.value).toBe("auto")
    expect(
      Array.from(select.querySelectorAll("option")).map((o) =>
        o.textContent?.trim()
      )
    ).toContain("Auto arbitration")
    // Fetch footer carries no Search-only controls.
    expect(
      within(footer).queryByRole("spinbutton", { name: "Number of results" })
    ).toBeNull()
    expect(
      within(footer).queryByRole("group", { name: /search depth/i })
    ).toBeNull()
    expect(footer.textContent).not.toMatch(/Suggestions:/)
    expect(footer.textContent).not.toMatch(/Results:/)
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
      /Enter a URL to fetch/i
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
    expect(shellSource).toContain("focus-within:")
    expect(shellSource).toContain("motion-reduce:transition-none")
    expect(shellSource).toContain("text-[13px]")
    expect(shellSource).toContain("text-[var(--muted)]")
    // Compatibility shell re-exports the canonical primitive.
    const composerShim = readFileSync(composerShimPath, "utf8")
    expect(composerShim).toContain("ComposerShell")
    expect(composerShim).toContain("shared/ui/ComposerShell")

    // Playground imports the shell for Fetch ONLY.
    expect(playgroundSource).toMatch(
      /from\s+["']@\/components\/common\/ComposerShell["']|from\s+["']\.\.\/common\/ComposerShell["']/
    )
    expect(playgroundSource).toContain("ComposerShell")
    expect(playgroundSource).toMatch(/testIdPrefix\s*=\s*["']fetch["']/)
    // Search is NOT migrated: no search prefix, inline seams intact.
    expect(playgroundSource).not.toMatch(/testIdPrefix\s*=\s*["']search["']/)
    expect(playgroundSource).toContain('data-testid="search-composer"')
    expect(playgroundSource).toContain('data-testid="fetch-layout"')
    expect(playgroundSource).toContain("hasFetchContent")
    // No stray composer files: only the shared shell.
    const commonFiles: string[] = existsSync(commonDir)
      ? readdirSync(commonDir)
      : []
    expect(commonFiles.filter((f) => /composer/i.test(f))).toEqual([
      "ComposerShell.tsx",
    ])
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
    expect(names).toContain("px-5")
    expect(names).toContain("py-2")
    expect(names).not.toContain("px-4")
    expect(names).not.toContain("py-1.5")

    const input = screen.getByPlaceholderText(
      /Search across all providers/i
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
    expect(composer.className).toContain("focus-within:")
    expect(
      composer.contains(screen.getByPlaceholderText(/Search across all providers/i))
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
      /Search across all providers/i
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

  it("PG-S5 number contract intact (Results 6, no Depth, default limit 6 auto)", async () => {
    const { stub } = renderWithBackend()
    await readyForSearch()

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
    expect(screen.queryByRole("group", { name: /search depth/i })).toBeNull()

    const input = screen.getByPlaceholderText(
      /Search across all providers/i
    ) as HTMLInputElement
    fireEvent.change(input, { target: { value: "pg-s5 guard query" } })
    fireEvent.click(screen.getByRole("button", { name: "Search", exact: true }))

    await waitFor(() => {
      expect(stub.requestsTo("/search")).toHaveLength(1)
    })
    expect(stub.requestsTo("/search")[0].body).toEqual({
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
      screen.getByRole("heading", { name: "Search Playground" })
    ).toBeInTheDocument()
    await gotoFetch()
    // Header persists across the Fetch hero/docked states.
    expect(
      screen.getByRole("heading", { name: "Search Playground" })
    ).toBeInTheDocument()

    // R-Strategy + R-Sim (blessed churn, NOT a regression): the Simulator
    // now composes via the shared ComposerShell inside a simulator-layout
    // hero/dock wrapper (Search/Fetch Tab pattern).
    expect(simulatorSource).toContain("SegmentedControl")
    expect(simulatorSource).toContain("Simulate route")
    expect(simulatorSource).toContain("ComposerShell")
    expect(simulatorSource).toContain("simulator-layout")
    expect(simulatorSource).not.toContain("fetch-layout")
    expect(simulatorSource).not.toContain("fetch-composer")
    expect(simulatorSource).not.toContain("search-composer")

    // Fetching logic untouched: execution start-clear + trim + routing
    // (canonical owner is the execution domain; the context wires runFetch).
    expect(executionSource).toContain("setActiveFetch(null)")
    expect(executionSource).toContain("setFetchError(null)")
    expect(executionSource).toContain("setIsFetching(true)")
    expect(executionSource).toContain("url: request.url.trim()")
    expect(executionSource).toContain("max_chars: null")
    expect(executionSource).toMatch(
      /mode:\s*request\.providerId\s*\?\s*["']require["']\s*:\s*["']auto["']/
    )
    expect(contextSource).toContain("FreeSearchInner")
    // Playground fetch call contract untouched (markdown/4000 + trims).
    expect(playgroundSource).toContain('format: "markdown"')
    expect(playgroundSource).toContain("timeoutMs: 4000")
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

  it("SearchPlayground shell re-exports PlaygroundPage without forking UI", () => {
    expect(playgroundShim).toContain("PlaygroundPage")
    expect(playgroundShim).toContain("SearchPlayground")
    expect(playgroundShim).toContain("features/playground/ui/PlaygroundPage")
  })

  it("RouteSimulator shell re-exports the routing feature without forking UI", () => {
    expect(simulatorShim).toContain("RouteSimulator")
    expect(simulatorShim).toContain("features/routing/ui/RouteSimulator")
  })
})
