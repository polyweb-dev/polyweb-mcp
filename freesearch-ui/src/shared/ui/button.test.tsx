import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { expect, it, vi } from "vitest"
import { Button } from "./button"

it("prevents duplicate submissions and shows the pending label", async () => {
  const submit = vi.fn()
  const { rerender } = render(<Button onClick={submit}>Save</Button>)
  await userEvent.click(screen.getByRole("button", { name: "Save" }))
  rerender(<Button onClick={submit} pending>Save</Button>)
  const button = screen.getByRole("button", { name: "Saving…" })
  expect(button).toBeDisabled()
  expect(button).toHaveAttribute("aria-busy", "true")
  await userEvent.click(button)
  expect(submit).toHaveBeenCalledTimes(1)
})
