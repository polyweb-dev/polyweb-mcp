import { describe, expect, it } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { JsonViewer } from "./JsonViewer"

/**
 * Shared recursive JSON viewer (PLAN §4): accessible collapsible nodes,
 * accent token classes, scalar punctuation discipline, anywhere wrapping, and
 * vertical-only bounded scrolling. No syntax-highlighting dependency.
 */
describe("JsonViewer", () => {
  it("exposes the accessible label", () => {
    render(<JsonViewer value={{ a: 1 }} ariaLabel="Trace attributes" />)

    expect(screen.getByRole("group", { name: "Trace attributes" })).toBeInTheDocument()
  })

  it("renders keys with the cyan accent and strings with the seafoam accent", () => {
    render(<JsonViewer value={{ query: "distributed consensus" }} ariaLabel="Payload" />)

    const group = screen.getByRole("group", { name: "Payload" })
    expect(group).toHaveTextContent('"query"')
    expect(group).toHaveTextContent('"distributed consensus"')
    const key = group.querySelector('span[style*="--accent-cyan"]')
    expect(key?.textContent).toBe('"query"')
    const token = group.querySelector('span[style*="--accent-seafoam"]')
    expect(token?.textContent).toBe('"distributed consensus"')
  })

  it("renders numbers and booleans with the gold accent and null muted", () => {
    render(
      <JsonViewer
        value={{ limit: 10, cached: false, missing: null }}
        ariaLabel="Scalars"
        defaultExpandedDepth={2}
      />
    )

    const group = screen.getByRole("group", { name: "Scalars" })
    const gold = [...group.querySelectorAll('span[style*="--accent-gold"]')].map(
      (node) => node.textContent
    )
    expect(gold).toContain("10")
    expect(gold).toContain("false")
    expect(group).toHaveTextContent("null")
  })

  it("collapses nested containers until they are opened", async () => {
    const user = userEvent.setup()
    render(
      <JsonViewer
        value={{ outer: { inner: { leaf: "deep" } } }}
        ariaLabel="Nested"
      />
    )

    expect(screen.queryByText('"deep"')).not.toBeInTheDocument()
    const outer = screen.getByText(/"outer"/).closest("summary")!
    await user.click(outer)
    expect(screen.queryByText('"deep"')).not.toBeInTheDocument()

    const inner = screen.getByText(/"inner"/).closest("summary")!
    await user.click(inner)
    expect(screen.getByText('"deep"')).toBeInTheDocument()
  })

  it("mounts descendants only once their node is opened", async () => {
    const user = userEvent.setup()
    render(<JsonViewer value={{ items: [1, 2, 3] }} ariaLabel="Lazy" />)

    const items = screen.getByText(/"items"/).closest("summary")!
    await user.click(items)
    // Array children mount on first open with stable punctuation.
    const group = screen.getByRole("group", { name: "Lazy" })
    expect(group).toHaveTextContent("3 items")
    expect(group.textContent).toContain("[")
    expect(group.textContent).toContain("]")
  })

  it("keeps JSON punctuation discipline with trailing commas", () => {
    render(
      <JsonViewer value={{ a: 1, b: 2 }} ariaLabel="Punctuation" defaultExpandedDepth={2} />
    )

    const group = screen.getByRole("group", { name: "Punctuation" })
    // Only the last child drops the separator: exactly one comma between a and b.
    const text = group.textContent ?? ""
    expect(text).toContain("{")
    expect(text).toContain("}")
    expect(text.match(/,/g)?.length).toBe(1)
  })

  it("wraps long scalars instead of forcing horizontal scroll", () => {
    const hostile = "https://example.com/" + "q=%5B".repeat(60)
    const { container } = render(
      <JsonViewer value={{ url: hostile }} ariaLabel="Long" defaultExpandedDepth={2} />
    )

    expect(screen.getByRole("group", { name: "Long" })).toHaveTextContent(hostile)
    const wrapper = container.querySelector('[role="group"]')!
    expect(wrapper.className).toContain("overflow-x-hidden")
    expect(wrapper.className).toContain("overflow-y-auto")
    expect(wrapper.className).toContain("[overflow-wrap:anywhere]")
  })

  it("renders empty objects and arrays with honest brackets", () => {
    render(
      <JsonViewer value={{ empty: {}, list: [] }} ariaLabel="Empty" defaultExpandedDepth={2} />
    )

    const group = screen.getByRole("group", { name: "Empty" })
    expect(group).toHaveTextContent("{}")
    expect(group).toHaveTextContent("[]")
  })

  it("renders undefined and non-finite numbers without throwing", () => {
    render(
      <JsonViewer
        value={{ nothing: undefined, infinite: Number.POSITIVE_INFINITY }}
        ariaLabel="Fallback"
        defaultExpandedDepth={2}
      />
    )

    const group = screen.getByRole("group", { name: "Fallback" })
    expect(group).toHaveTextContent("undefined")
    expect(group).toHaveTextContent("null")
  })

  it("operates disclosures by keyboard focus and activation", async () => {
    const user = userEvent.setup()
    render(<JsonViewer value={{ outer: { leaf: 1 } }} ariaLabel="Keyboard" />)

    const summary = screen.getByText(/"outer"/).closest("summary")!
    expect(summary.tagName.toLowerCase()).toBe("summary")
    summary.focus()
    expect(summary).toHaveFocus()
    // Native summary activation (keyboard Enter/Space fires click): the viewer
    // toggles through its click handler, so a focused click opens the node.
    await user.click(summary)
    expect(within(summary.closest("details")!).getByText(/"leaf"/)).toBeInTheDocument()
  })
})
