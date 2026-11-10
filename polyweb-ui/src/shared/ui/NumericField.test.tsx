import { useState } from "react"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { expect, it, vi } from "vitest"
import { NumericField } from "./NumericField"

it("accepts decimal values and retains native numeric validation", async () => {
  function Example() {
    const [value, setValue] = useState("")
    return <NumericField id="budget" label="Budget" value={value} onChange={setValue} min="0" step="0.01" prefix="$" />
  }
  render(<Example />)
  const input = screen.getByRole("spinbutton", { name: "Budget" })
  await userEvent.type(input, "12.34")
  expect(input).toHaveValue(12.34)
  expect(input).toBeValid()
  expect(screen.getByText("$")).toHaveAttribute("aria-hidden", "true")
})

it("associates validation and disables the numeric control during a save", () => {
  render(<NumericField id="balance" label="Balance" value="-1" onChange={() => {}}
    prefix="$" error="Balance must be positive" disabled />)
  const input = screen.getByRole("spinbutton", { name: "Balance" })
  expect(input).toBeDisabled()
  expect(input).toHaveAttribute("aria-invalid", "true")
  expect(input).toHaveAccessibleDescription("Balance must be positive")
})

it("forwards blur to the caller and works without an onBlur handler", async () => {
  const onBlur = vi.fn()
  const { rerender } = render(<NumericField id="count" label="Count" value="3" onChange={() => {}} onBlur={onBlur} />)
  await userEvent.click(screen.getByRole("spinbutton", { name: "Count" }))
  await userEvent.tab()
  expect(onBlur).toHaveBeenCalledOnce()
  rerender(<NumericField id="count" label="Count" value="3" onChange={() => {}} />)
  await userEvent.click(screen.getByRole("spinbutton", { name: "Count" }))
  await userEvent.tab()
  expect(onBlur).toHaveBeenCalledOnce()
})
