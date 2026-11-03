import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { SecretInput } from "./SecretInput"

describe("SecretInput", () => {
  it("is a write-only password field the browser does not remember", async () => {
    const onChange = vi.fn()
    render(<SecretInput id="key" label="API key" value="" onChange={onChange} />)
    const input = screen.getByLabelText("API key")
    expect(input).toHaveAttribute("type", "password")
    expect(input).toHaveAttribute("autocomplete", "off")
    expect(input).toHaveAttribute("spellcheck", "false")
    await userEvent.type(input, "k")
    expect(onChange).toHaveBeenCalledWith("k")
  })

  it("shows the controlled value only", () => {
    const { rerender } = render(<SecretInput id="key" label="New API key" value="abc" onChange={() => {}} />)
    expect(screen.getByLabelText("New API key")).toHaveValue("abc")
    rerender(<SecretInput id="key" label="New API key" value="" onChange={() => {}} />)
    expect(screen.getByLabelText("New API key")).toHaveValue("")
  })
})
