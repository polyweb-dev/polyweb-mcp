import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { IdentityLines } from "./IdentityLines"

/**
 * IdentityLines: strong primary plus a visible muted contact line, so two
 * same-name rows stay distinguishable where a row overlay covers hover titles.
 */
describe("IdentityLines", () => {
  it("shows the primary with its contact as the title and as a visible second line", () => {
    render(<IdentityLines primary="Ada Lovelace" secondary="Platform team" />)

    expect(screen.getByText("Ada Lovelace")).toHaveAttribute(
      "title",
      "Ada Lovelace (Platform team)"
    )
    expect(screen.getByText("Platform team")).toBeInTheDocument()
  })

  it("hides the second line when it adds nothing", () => {
    const { container, rerender } = render(
      <IdentityLines primary="Ada Lovelace" secondary="Ada Lovelace" />
    )
    expect(container.querySelectorAll("span span")).toHaveLength(1)

    rerender(<IdentityLines primary="Ada Lovelace" secondary={null} />)
    expect(screen.getByText("Ada Lovelace")).toHaveAttribute("title", "Ada Lovelace")
    expect(container.querySelectorAll("span span")).toHaveLength(1)
  })

  it("shows a monospace token after the lead text on the second line", () => {
    const { container } = render(
      <IdentityLines primary="test-key" secondary="API key ·" secondaryMono="pw_live_ab12" />
    )

    expect(container).toHaveTextContent("test-keyAPI key · pw_live_ab12")
    expect(screen.getByText("pw_live_ab12")).toHaveClass("font-mono")
    expect(screen.getByText("test-key")).toHaveAttribute("title", "test-key (API key · pw_live_ab12)")
  })

  it("shows the monospace token alone when there is no lead text", () => {
    const { container } = render(<IdentityLines primary="API key" secondaryMono="pw_live_ab12" />)

    expect(container).toHaveTextContent("API keypw_live_ab12")
  })

  it("uses the explicit detail as the primary title when provided", () => {
    render(<IdentityLines primary="ada" secondary="Platform team" detail="ada (platform)" />)

    expect(screen.getByText("ada")).toHaveAttribute("title", "ada (platform)")
  })
})
