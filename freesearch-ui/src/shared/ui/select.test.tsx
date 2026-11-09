import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"
import { Select } from "./select"

describe("Select popup alignment", () => {
  it("aligns an end popup to the trigger and caps its width", async () => {
    render(<Select ariaLabel="Order" align="end" value="a" options={[{ value: "a", label: "First" }, { value: "b", label: "Second" }]} onValueChange={vi.fn()} />)
    await userEvent.click(screen.getByRole("combobox", { name: "Order" }))
    expect(screen.getByRole("listbox")).toHaveClass("right-0", "max-w-[calc(100vw-2rem)]")
    expect(screen.getByRole("listbox")).not.toHaveClass("left-0")
  })

  it("preserves the default placement", async () => {
    render(<Select ariaLabel="Order" value="a" options={[{ value: "a", label: "First" }]} onValueChange={vi.fn()} />)
    await userEvent.click(screen.getByRole("combobox", { name: "Order" }))
    expect(screen.getByRole("listbox")).toHaveClass("left-0", "right-0")
  })
})
