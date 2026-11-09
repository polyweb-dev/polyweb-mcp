import { render, screen } from "@testing-library/react"
import { expect, it } from "vitest"
import { TraceFetchDocument } from "./TraceFetchDocument"

it("shows the exact stored document as raw text", () => {
  const content = "# Guide\n\n**Notice:** Read the [docs](/docs).\n\n- Search\n- Fetch\n\n```js\nconst value = 1\n```"
  render(<TraceFetchDocument input="https://example.com" output={{ kind: "fetch_document", title: "Document", url: "https://example.com", content, contentLength: content.length, truncated: false }} />)
  expect(screen.queryByRole("heading", { name: "Guide" })).toBeNull()
  expect(screen.queryByRole("link", { name: "docs" })).toBeNull()
  expect(screen.queryByRole("button", { name: /Rendered|Raw/ })).toBeNull()
  expect(screen.getByText((_, element) => element?.tagName === "PRE" && element.textContent === content)).toBeInTheDocument()
})

it("keeps embedded HTML and script links inert", () => {
  const content = '<script>alert(1)</script>\n\n[Run](javascript:alert)\n\n![Image](https://example.com/image.png)'
  const { container } = render(<TraceFetchDocument input={null} output={{ kind: "fetch_document", title: "Document", url: "https://example.com", content, contentLength: content.length, truncated: false }} />)
  expect(container.querySelector("script")).toBeNull()
  expect(screen.queryByRole("link", { name: "Run" })).toBeNull()
  expect(screen.queryByRole("img")).toBeNull()
  expect(screen.getByText((_, element) => element?.tagName === "PRE" && element.textContent === content)).toBeInTheDocument()
})
