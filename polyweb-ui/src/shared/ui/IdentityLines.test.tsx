import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { IdentityLines } from "./IdentityLines"

/**
 * IdentityLines: strong primary plus a visible muted contact line, so two
 * same-name rows stay distinguishable where a row overlay covers hover titles.
 */
describe("IdentityLines", () => {
  it("shows the primary with the full contact as its title and the contact as a visible second line", () => {
    render(<IdentityLines primary="Ada Lovelace" secondary="ada@example.com" />)

    expect(screen.getByText("Ada Lovelace")).toHaveAttribute(
      "title",
      "Ada Lovelace (ada@example.com)"
    )
    expect(screen.getByText("ada@example.com")).toBeInTheDocument()
  })

  it("hides the second line when the contact adds nothing", () => {
    const { container, rerender } = render(
      <IdentityLines primary="ada@example.com" secondary="ada@example.com" />
    )
    expect(container.querySelectorAll("span span")).toHaveLength(1)

    rerender(<IdentityLines primary="Ada Lovelace" secondary={null} />)
    expect(screen.getByText("Ada Lovelace")).toHaveAttribute("title", "Ada Lovelace")
    expect(screen.queryByText("ada@example.com")).not.toBeInTheDocument()
  })

  it("uses the existing contact detail helper output as the primary title when provided", () => {
    render(
      <IdentityLines
        primary="ada"
        secondary="ada@example.com"
        detail="ada (ada@work.example)"
      />
    )

    // The explicit detail wins even though the generated contact would differ.
    expect(screen.getByText("ada")).toHaveAttribute("title", "ada (ada@work.example)")
  })
})
