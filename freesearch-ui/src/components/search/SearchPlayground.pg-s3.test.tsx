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
 * Plan under test (CONFIRMED, freesearch-ui/ ONLY):
 *   - search-composer box (elevated + border + rounded-xl + padding + shadow
 *     + focus-within signal, Search-mode ONLY, Fetch bare);
 *   - division idle + docked (results render AFTER the composer);
 *   - internal divider + footer tray (suggestions + provider + depth INSIDE
 *     the box, muted 13px);
 *   - focus-within + motion-reduce;
 *   - docked-top + same-form + PG-S1 contract intact;
 *   - PG-S2 button lock intact.
 *   - reusable pattern across three (Search now; Fetch/Simulator later --
 *     name seams only, do NOT build shared file).
 *
 * AC mapping:
 *   AC-PG-S3-1  Search-mode composer box: data-testid="search-composer"
 *               present ONLY in Search mode; carries elevated bg + border +
 *               rounded-xl + padding + shadow + focus-within signal; input
 *               inside is borderless (no bare underline); Fetch mode is bare
 *               (no composer). Seam named in source, gated on
 *               mode === "search", with NO shared composer file.
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
 *               Search ONLY, px-5 py-2 inline-flex gap, input pr-32/36 floor,
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
const playgroundSource = readFileSync(
  path.resolve(testDir, "./SearchPlayground.tsx"),
  "utf8"
)
const searchDir = testDir
const commonDir = path.resolve(testDir, "../common")

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
  expect(cls).toContain("focus-within:")
  expect(cls).toContain("signal")
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
    const input = screen.getByPlaceholderText(/Search across all providers/i)
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

    const fetchInput = screen.getByPlaceholderText(/Enter a URL to fetch/i)
    expect(fetchInput).toBeInTheDocument()
    // Fetch does NOT adopt the search box (reusable pattern later, bare now).
    expect(screen.queryByTestId("search-composer")).toBeNull()
    expect(screen.queryByTestId("search-composer-footer")).toBeNull()
    const fetchButton = screen.getByRole("button", {
      name: "Fetch",
      exact: true,
    })
    expect(fetchButton.querySelector("svg")).toBeNull()
  })

  it("names the search seam in SearchPlayground source gated on Search mode with NO shared composer file", () => {
    // Seam names only -- Search now, Fetch/Simulator later.
    expect(playgroundSource).toContain("search-composer")
    expect(playgroundSource).toContain("search-composer-footer")
    expect(playgroundSource).toContain("search-composer-divider")
    // Gated on Search mode only (Fetch stays bare by construction).
    expect(playgroundSource).toMatch(/mode\s*===\s*["']search["']/)
    // NO shared component extraction in this bullet.
    const bannedImport =
      /from\s+["'][^"']*[Cc]omposer[^"']*["']|import\s+[^;]*Composer/.test(
        playgroundSource
      )
    expect(bannedImport).toBe(false)
    const commonFiles: string[] = existsSync(commonDir)
      ? readdirSync(commonDir)
      : []
    expect(
      commonFiles.filter((f) => /composer/i.test(f))
    ).toEqual([])
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
      "hero"
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
    // eslint-disable-next-line no-bitwise
    expect(composer!.compareDocumentPosition(firstResult) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })
})

describe("PG-S3 AC-PG-S3-3: internal divider + footer tray owns suggestions/provider/depth at muted 13px", () => {
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

  it("nests suggestions + provider + depth INSIDE the footer tray at muted 13px", async () => {
    renderWithBackend()
    await readyForSearch()

    const composer = screen.queryByTestId("search-composer")
    expect(composer).not.toBeNull()
    const footer = screen.queryByTestId("search-composer-footer")
    expect(footer).not.toBeNull()
    expect(composer!.contains(footer!)).toBe(true)

    // All three controls live INSIDE the footer (ChatGPT tray aesthetic).
    const suggestions = within(footer!).getByText(/Suggestions:/i)
    expect(suggestions).toBeInTheDocument()
    const suggestionBtn = within(footer!).getByRole("button", {
      name: /python async search aggregator/i,
    })
    expect(suggestionBtn).toBeInTheDocument()
    const provider = within(footer!).getByRole("combobox")
    expect(provider).toBeInTheDocument()
    const depthGroup = within(footer!).getByRole("group", {
      name: /search depth/i,
    })
    expect(depthGroup).toBeInTheDocument()
    expect(
      within(depthGroup).getByRole("button", { name: "Balanced" })
    ).toBeInTheDocument()

    // Footer tray is muted 13px (secondary controls, not body copy).
    expect(footer!.className).toContain("text-[13px]")
    expect(footer!.className).toContain("text-[var(--muted)]")

    // Nothing leaks outside: the composer owns every instance.
    expect(
      screen.getByPlaceholderText(/Search across all providers/i).closest("form")
    ).not.toBeNull()
    const outsideSuggestions = Array.from(
      document.querySelectorAll("body *")
    ).filter(
      (el) =>
        el.textContent?.includes("Suggestions:") &&
        !footer!.contains(el) &&
        el.textContent!.trim().startsWith("Suggestions:")
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
    expect(cls).toContain("focus-within:")
    expect(cls).toContain("signal")
    expect(cls).not.toMatch(/(^|\s)focus:/)
    // Motion hygiene mirrors the PG-S1 layout wrapper.
    expect(tokens(cls)).toContain("transition-all")
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
    const composerBefore = screen.queryByTestId("search-composer")
    expect(composerBefore).not.toBeNull()

    const inputBefore = screen.getByPlaceholderText(
      /Search across all providers/i
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
      /Search across all providers/i
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
      screen.getByRole("heading", { name: "Search Playground" })
    ).toBeInTheDocument()

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
    expect(fetchButton.querySelector("svg")).toBeNull()
    expect(fetchButton.textContent?.trim()).toBe("Fetch")
  })
})
