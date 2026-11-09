import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { expect, it } from "vitest"
import { TraceFetchDocument } from "./TraceFetchDocument"

it("renders a stored document by default and offers its exact raw text", async () => {
  const content = "# Guide\n\n**Notice:** Read the [docs](/docs).\n\n- Search\n- Fetch\n\n```js\nconst value = 1\n```"
  render(<TraceFetchDocument input="https://example.com" output={{ kind: "fetch_document", title: "Document", url: "https://example.com", content, contentLength: content.length, truncated: false }} />)
  expect(screen.getByRole("heading", { name: "Guide" })).toBeInTheDocument()
  expect(screen.getByRole("link", { name: "docs" })).toHaveAttribute("href", "https://example.com/docs")
  expect(screen.getAllByRole("listitem")).toHaveLength(2)
  expect(screen.getByText("const value = 1")).toBeInTheDocument()
  await userEvent.click(screen.getByRole("button", { name: "Raw" }))
  expect(screen.queryByRole("heading", { name: "Guide" })).toBeNull()
  expect(screen.getByText((_, element) => element?.tagName === "PRE" && element.textContent === content)).toBeInTheDocument()
})

it("keeps embedded HTML and script links inert", () => {
  const content = '<script>alert(1)</script>\n\n[Run](javascript:alert)\n\n![Image](https://example.com/image.png)'
  const { container } = render(<TraceFetchDocument input={null} output={{ kind: "fetch_document", title: "Document", url: "https://example.com", content, contentLength: content.length, truncated: false }} />)
  expect(container.querySelector("script")).toBeNull()
  expect(screen.queryByRole("link", { name: "Run" })).toBeNull()
  expect(screen.queryByRole("img")).toBeNull()
  expect(screen.getByText("Run")).toBeInTheDocument()
})
