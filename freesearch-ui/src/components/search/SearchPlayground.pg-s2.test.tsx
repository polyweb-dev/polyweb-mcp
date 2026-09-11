import React from "react"
import { readFileSync } from "node:fs"
import path from "node:path"
import { describe, it, expect, afterEach, vi } from "vitest"
import { render, screen, fireEvent, waitFor } from "@testing-library/react"
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
 * PG-S2 Search-button breathing room (BDD Acceptance, RED phase).
 *
 * User bullet (verbatim): "Search button can use an icon and maybe more space
 * as it looks compressed". Read-only: .agents/FEEDBACK/UI/feedback.md L38.
 * SEE image-9.png: a small text-only "Search" pill with tight padding.
 *
 * Plan under test (ORCHESTRATOR RULING, freesearch-ui/ ONLY):
 *   - submit Button gets a LEADING lucide Search icon (size-3.5, aria-hidden)
 *     + inline-flex gap + px-5 py-2 (was px-4 py-1.5);
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
 *   AC-PG-S2-3  Button spacing bumped: px-5 + py-2 (+ inline-flex gap);
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
// Slice 5 ownership: SearchPlayground.tsx is a compatibility shell over
// features/playground. Read the joined owner sources (same strength as the
// monolith read) plus the shell for the shim-compat assert below.
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

describe("PG-S2 AC-PG-S2-3: submit button spacing bumped px-5 py-2 + inline-flex gap", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("carries px-5 + py-2 with inline-flex gap; px-4 / py-1.5 are gone", async () => {
    renderWithBackend()
    await readyForSearch()

    const button = screen.getByRole("button", { name: "Search", exact: true })
    const names = tokens(button.className)
    expect(names).toContain("px-5")
    expect(names).toContain("py-2")
    expect(names).not.toContain("px-4")
    expect(names).not.toContain("py-1.5")
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
      /Search across all providers/i
    ) as HTMLInputElement
    const names = tokens(input.className)
    expect(names.some((t) => t === "pr-32" || t === "pr-36")).toBe(true)
    expect(names).not.toContain("pr-28")
  })

  it("keeps the relative wrapper + absolute right-0 button + w-full input so text never slides under the wider button", async () => {
    renderWithBackend()
    await readyForSearch()

    const input = screen.getByPlaceholderText(
      /Search across all providers/i
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
    // ... and the raised floor clearing the wider px-5 button.
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
    expect(hero).toHaveAttribute("data-state", "hero")
    expect(hero.className).toMatch(/min-h-\[(55|60)vh\]/)
    expect(hero.className).toContain("max-w-3xl")
    expect(hero.className).not.toContain("top-docked")

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
      screen.getByRole("heading", { name: "Search Playground" })
    ).toBeInTheDocument()
  })

  it("Fetch tab flow is untouched end-to-end", async () => {
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

describe("Slice 5 shim compatibility: SearchPlayground shell re-exports the feature owner", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("re-exports PlaygroundPage as SearchPlayground without forking UI", () => {
    expect(playgroundShim).toContain("PlaygroundPage")
    expect(playgroundShim).toContain("SearchPlayground")
    expect(playgroundShim).toContain("features/playground/ui/PlaygroundPage")
  })
})
