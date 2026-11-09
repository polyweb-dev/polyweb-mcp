import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { ProviderBadge } from "./ProviderBadge"

/**
 * ProviderBadge (PLAN §4 R5): one provider identity everywhere — the catalog
 * logo followed by the provider name. Presentation only.
 */
describe("ProviderBadge", () => {
  it("renders the logo followed by the provider name in DOM order", () => {
    const { container } = render(<ProviderBadge providerId="tavily" name="Tavily" />)

    const logo = container.querySelector('[data-testid="provider-logo-tavily"]')
    const name = screen.getByText("Tavily")
    expect(logo).not.toBeNull()
    expect(logo?.tagName).toBe("IMG")
    expect(logo?.compareDocumentPosition(name)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING
    )
  })

  it("passes className through to the outer badge element", () => {
    const { container } = render(
      <ProviderBadge providerId="exa" name="Exa" className="my-badge" />
    )

    const outer = container.firstElementChild
    expect(outer?.tagName).toBe("SPAN")
    expect(outer).toHaveClass("my-badge")
    expect(outer).toHaveClass("inline-flex")
  })

  it("passes logoClassName through to the logo image", () => {
    render(
      <ProviderBadge
        providerId="brave"
        name="Brave Search"
        logoClassName="my-logo"
      />
    )

    expect(screen.getByTestId("provider-logo-brave")).toHaveClass("my-logo")
  })

  it("renders the given display name verbatim after the logo", () => {
    const { container } = render(
      <ProviderBadge providerId="youcom" name="You.com" />
    )

    const name = screen.getByText("You.com")
    const logo = container.querySelector('[data-testid="provider-logo-youcom"]')
    expect(logo).not.toBeNull()
    expect(logo?.compareDocumentPosition(name)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING
    )
  })
})
