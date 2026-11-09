import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { PageHeader } from "./PageHeader"

describe("PageHeader", () => {
  it("renders the title as an h2", () => {
    render(<PageHeader title="Members" />)
    const heading = screen.getByRole("heading", { name: "Members" })
    expect(heading.tagName).toBe("H2")
  })

  it("shows the description when one is given", () => {
    render(<PageHeader title="Playground" description="Run search and fetch through Alpha's providers." />)
    expect(screen.getByText("Run search and fetch through Alpha's providers.")).toBeInTheDocument()
  })

  it("omits the description line without one", () => {
    const { container } = render(<PageHeader title="Usage" />)
    expect(container.querySelectorAll("p")).toHaveLength(0)
  })

  it("renders actions on the right", () => {
    render(<PageHeader title="Providers" actions={<button type="button">Add provider key</button>} />)
    expect(screen.getByRole("button", { name: "Add provider key" })).toBeInTheDocument()
  })
})
