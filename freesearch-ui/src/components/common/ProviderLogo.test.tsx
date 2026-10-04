import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import { ProviderLogo } from "./ProviderLogo"

describe("ProviderLogo", () => {
  it("renders the correct webp logo for known providers by id", () => {
    render(<ProviderLogo providerId="brave" />)
    const img = screen.getByTestId("provider-logo-brave")
    expect(img).toBeInTheDocument()
    expect(img.tagName.toLowerCase()).toBe("img")
    expect(img).toHaveAttribute("aria-hidden", "true")
  })

  it("renders the correct logo for known providers by name", () => {
    render(<ProviderLogo name="You.com" />)
    const img = screen.getByTestId("provider-logo-you.com")
    expect(img).toBeInTheDocument()
  })

  it("renders the correct webp logo for tinyfish by providerId", () => {
    render(<ProviderLogo providerId="tinyfish" />)
    const img = screen.getByTestId("provider-logo-tinyfish")
    expect(img).toBeInTheDocument()
    expect(img.tagName.toLowerCase()).toBe("img")
    expect(img).toHaveAttribute("aria-hidden", "true")
    expect(img.getAttribute("src")).toContain("tinyfish.webp")
  })

  it("renders the correct webp logo for tinyfish by name", () => {
    render(<ProviderLogo name="Tinyfish" />)
    const img = screen.getByTestId("provider-logo-tinyfish")
    expect(img).toBeInTheDocument()
  })

  it("renders a fallback avatar letter for unknown providers", () => {
    render(<ProviderLogo providerId="unknown_engine" name="Custom Engine" />)
    const fallback = screen.getByTestId("provider-logo-fallback")
    expect(fallback).toBeInTheDocument()
    expect(fallback.textContent).toBe("C")
  })

  it("returns null when no providerId or name is provided", () => {
    const { container } = render(<ProviderLogo />)
    expect(container.firstChild).toBeNull()
  })
})
