import React from "react"
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

function expectTransitionClasses(wrapper: HTMLElement) {
  // Exact animation contract from the plan — all four tokens required.
  expect(wrapper.className).toContain("transition-all")
  expect(wrapper.className).toContain("duration-300")
  expect(wrapper.className).toContain("ease-out")
  expect(wrapper.className).toContain("motion-reduce:transition-none")
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
      screen.getByPlaceholderText(/Search across all providers/i)
    ).toBeInTheDocument()
    expect(screen.queryByText("Live backend result one")).not.toBeInTheDocument()
    expect(screen.queryByText(/no provider is configured/i)).not.toBeInTheDocument()

    const wrapper = screen.getByTestId("search-layout")
    expect(wrapper).toHaveAttribute("data-state", "hero")
    // Hero geometry: tall centered column, constrained width.
    expect(wrapper.className).toMatch(/min-h-\[(55|60)vh\]/)
    expect(wrapper.className).toContain("max-w-3xl")
    expectTransitionClasses(wrapper)
    // The request form is the wrapped content — same element, not a copy.
    expect(
      wrapper.querySelector('input[placeholder*="Search across all providers"]')
    ).not.toBeNull()
    // Hero must not carry the docked marker.
    expect(wrapper.className).not.toContain("top-docked")
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
    expect(wrapperBefore).toHaveAttribute("data-state", "hero")

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
      screen.getByPlaceholderText(/Search across all providers/i)
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
      .getByPlaceholderText(/Search across all providers/i)
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
      expect(screen.getByText(/no provider is configured/i)).toBeInTheDocument()
    })
    // Error counts as content: the hero must be gone.
    const wrapper = screen.getByTestId("search-layout")
    expect(wrapper).toHaveAttribute("data-state", "docked")
    expect(wrapper.className).toContain("top-docked")
    expectTransitionClasses(wrapper)
    // Form survives the failure; results stay absent.
    expect(
      screen.getByPlaceholderText(/Search across all providers/i)
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
      /Search across all providers/i
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
      /Search across all providers/i
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
      screen.getByRole("heading", { name: "Search Playground" })
    ).toBeInTheDocument()
    // Search submit button untouched (idle label).
    expect(
      screen.getByRole("button", { name: "Search", exact: true })
    ).toBeInTheDocument()

    // Fetching flow untouched end-to-end.
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
    // Fetch submit button returns to its idle label after completion.
    expect(
      screen.getByRole("button", { name: "Fetch", exact: true })
    ).toBeInTheDocument()
  })
})
