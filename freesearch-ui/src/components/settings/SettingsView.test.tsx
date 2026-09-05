import { describe, it, expect } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { SettingsView } from "./SettingsView"

describe("SettingsView", () => {
  const renderSettings = () =>
    render(
      <FreeSearchProvider>
        <SettingsView />
      </FreeSearchProvider>
    )

  it("renders all settings sections", () => {
    renderSettings()

    expect(screen.getByText("Fallback policy")).toBeInTheDocument()
    expect(screen.getByText("Provider registry")).toBeInTheDocument()
    expect(screen.getByText("API keys")).toBeInTheDocument()
    expect(screen.getByText("Cache")).toBeInTheDocument()
  })

  it("displays providers with their names", () => {
    renderSettings()

    expect(screen.getAllByText("Brave Search").length).toBeGreaterThan(0)
    expect(screen.getAllByText("Keenable").length).toBeGreaterThan(0)
    expect(screen.getAllByText("Tavily").length).toBeGreaterThan(0)
    expect(screen.getAllByText("Exa").length).toBeGreaterThan(0)
  })

  it("shows em-dash for providers that do not support fetch (e.g. Brave)", () => {
    renderSettings()

    // Brave and Exa are search-only, so they show "—" for fetch
    const dashElements = screen.getAllByText("—")
    expect(dashElements.length).toBeGreaterThan(0)
  })

  it("opens the add provider modal when clicking button", () => {
    renderSettings()

    const addBtn = screen.getByText("Add provider")
    fireEvent.click(addBtn)

    expect(screen.getByText("Register a custom or emerging search endpoint.")).toBeInTheDocument()
    expect(screen.getByPlaceholderText("e.g. kagi, searxng-local")).toBeInTheDocument()
  })

  it("renders fallback chaining switch", () => {
    renderSettings()

    const fallbackLabel = screen.getByText("Fallback chaining")
    expect(fallbackLabel).toBeInTheDocument()
  })
})
