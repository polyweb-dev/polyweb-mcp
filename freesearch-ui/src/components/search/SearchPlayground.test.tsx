import { describe, it, expect } from "vitest"
import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { SearchPlayground } from "./SearchPlayground"

describe("SearchPlayground", () => {
  const renderPlayground = () =>
    render(
      <FreeSearchProvider>
        <SearchPlayground />
      </FreeSearchProvider>
    )

  it("renders mode toggles and search form", () => {
    renderPlayground()

    // "Search" appears as both the mode toggle and the submit button
    expect(screen.getAllByText("Search").length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText("Fetch")).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/Search across all providers/i)).toBeInTheDocument()
  })

  it("switches to fetch mode when clicking Fetch", () => {
    renderPlayground()

    const fetchModeBtn = screen.getByText("Fetch")
    fireEvent.click(fetchModeBtn)

    expect(
      screen.getByPlaceholderText(/Enter a URL to fetch and convert/i)
    ).toBeInTheDocument()
  })

  it("populates query when clicking a quick suggestion", () => {
    renderPlayground()

    const pill = screen.getByText("keenable keyless free tier")
    fireEvent.click(pill)

    const input = screen.getByPlaceholderText(/Search across all providers/i) as HTMLInputElement
    expect(input.value).toBe("keenable keyless free tier")
  })

  it("executes search and displays results upon submission", async () => {
    renderPlayground()

    // Type a query first since the input starts empty now
    const input = screen.getByPlaceholderText(/Search across all providers/i) as HTMLInputElement
    fireEvent.change(input, { target: { value: "test query" } })

    const form = input.closest("form")!
    fireEvent.submit(form)

    await waitFor(
      () => {
        // Results now display as flat list with "match" text inline
        expect(screen.getAllByText(/match/i).length).toBeGreaterThan(0)
      },
      { timeout: 4000 }
    )
  })
})
